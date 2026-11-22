// A shared hidden virtual display on macOS for running GUI apps without
// disturbing someone using the computer: macOS renders windows on any active
// display, so tests, screenshots, recordings, and measurements run normally
// without opening windows on the user's screen.
//
// `hidden-display ensure` starts a detached background process that holds one
// per-user virtual display and records its PID, display ID, and origin in
// macOS's per-user temporary directory (`hidden-display`, or
// $HIDDEN_DISPLAY_STATE_DIR for isolated tests). Later calls reuse that display
// instead of attaching and detaching a virtual monitor on every run, which
// would make macOS reconfigure screens and jump the Dock. A file lock
// serializes concurrent callers. Changes to this file take effect after
// `hidden-display stop`.
//
// Usage:
//   hidden-display ensure   ensure the shared display is running; print `<id> <x> <y>`
//   hidden-display status   report whether it is running (exits 0 if running, 1 otherwise)
//   hidden-display stop     stop the running display and remove its state record
//
// Built on CGVirtualDisplay (1600 x 1000 points, 2x Retina pixels, 120 Hz) and
// placed past the far bottom-right corner of all active displays so the pointer
// does not wander onto it.
//
// clang -Wall -Wextra -fobjc-arc -framework Foundation -framework CoreGraphics \
//   hidden-display.m -o hidden-display

#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <libproc.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/proc.h>
#include <sys/proc_info.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

@interface CGVirtualDisplayDescriptor : NSObject
@property(retain, nonatomic) dispatch_queue_t queue;
@property(retain, nonatomic) NSString *name;
@property(nonatomic) unsigned int maxPixelsWide;
@property(nonatomic) unsigned int maxPixelsHigh;
@property(nonatomic) CGSize sizeInMillimeters;
@property(nonatomic) unsigned int productID;
@property(nonatomic) unsigned int vendorID;
@property(nonatomic) unsigned int serialNum;
@end

@interface CGVirtualDisplayMode : NSObject
- (instancetype)initWithWidth:(unsigned int)width
                       height:(unsigned int)height
                  refreshRate:(double)refreshRate;
@end

@interface CGVirtualDisplaySettings : NSObject
@property(retain, nonatomic) NSArray<CGVirtualDisplayMode *> *modes;
@property(nonatomic) unsigned int hiDPI;
@end

@interface CGVirtualDisplay : NSObject
@property(readonly, nonatomic) unsigned int displayID;
- (instancetype)initWithDescriptor:(CGVirtualDisplayDescriptor *)descriptor;
- (BOOL)applySettings:(CGVirtualDisplaySettings *)settings;
@end

static const unsigned int WIDE = 1600, HIGH = 1000;
static const uint32_t VENDOR_ID = 0x4844;
static const uint32_t PRODUCT_ID = 0x4844;
static const char *PROC_NAME = "hidden-display";
static const char *STATE_NAME = "hidden-display";
static const char *STATE_DIR_ENV = "HIDDEN_DISPLAY_STATE_DIR";

typedef struct {
  pid_t pid;
  CGDirectDisplayID display_id;
  int x;
  int y;
} DisplayState;

// Resolves one per-user location shared across shells and agent sessions:
// macOS's per-user temporary directory (`_CS_DARWIN_USER_TEMP_DIR`), which does
// not vary with per-process TMPDIR or XDG_RUNTIME_DIR overrides. Tests may set
// HIDDEN_DISPLAY_STATE_DIR to isolate state.
static bool resolve_paths(char *state_path, size_t state_sz, char *lock_path, size_t lock_sz) {
  char base[PATH_MAX];
  bool qualify_uid = false;

  const char *override = getenv(STATE_DIR_ENV);
  if (override != NULL && override[0] != '\0') {
    if (snprintf(base, sizeof(base), "%s", override) >= (int)sizeof(base)) return false;
  } else {
    size_t n = confstr(_CS_DARWIN_USER_TEMP_DIR, base, sizeof(base));
    if (n == 0 || n >= sizeof(base)) {
      const char *tmp = getenv("TMPDIR");
      if (tmp != NULL && tmp[0] != '\0') {
        if (snprintf(base, sizeof(base), "%s", tmp) >= (int)sizeof(base)) return false;
      } else {
        snprintf(base, sizeof(base), "/tmp");
        qualify_uid = true;
      }
    }
  }

  size_t len = strlen(base);
  while (len > 1 && base[len - 1] == '/') {
    base[--len] = '\0';
  }

  int s, l;
  if (qualify_uid) {
    unsigned long uid = (unsigned long)getuid();
    s = snprintf(state_path, state_sz, "%s/%s-%lu", base, STATE_NAME, uid);
    l = snprintf(lock_path, lock_sz, "%s/%s-%lu.lock", base, STATE_NAME, uid);
  } else {
    s = snprintf(state_path, state_sz, "%s/%s", base, STATE_NAME);
    l = snprintf(lock_path, lock_sz, "%s/%s.lock", base, STATE_NAME);
  }
  return s > 0 && (size_t)s < state_sz && l > 0 && (size_t)l < lock_sz;
}

static int open_and_lock(const char *lock_path, int op) {
  int fd = open(lock_path, O_CREAT | O_RDWR | O_CLOEXEC, 0600);
  if (fd < 0) {
    fprintf(stderr, "hidden-display: cannot open lock %s: %s\n", lock_path, strerror(errno));
    return -1;
  }
  while (flock(fd, op) != 0) {
    if (errno == EINTR) continue;
    fprintf(stderr, "hidden-display: cannot lock %s: %s\n", lock_path, strerror(errno));
    close(fd);
    return -1;
  }
  return fd;
}

static bool read_state(const char *state_path, DisplayState *out) {
  FILE *f = fopen(state_path, "r");
  if (f == NULL) return false;
  char buf[256];
  size_t n = fread(buf, 1, sizeof(buf) - 1, f);
  bool at_eof = feof(f) != 0 || fgetc(f) == EOF;
  fclose(f);
  if (n == 0 || !at_eof) return false;
  buf[n] = '\0';

  long long pid = 0;
  unsigned int display_id = 0;
  int x = 0, y = 0;
  int consumed = 0;
  if (sscanf(buf, "pid=%lld\ndisplay=%u\norigin=%d,%d%n", &pid, &display_id, &x, &y, &consumed) !=
      4) {
    return false;
  }
  for (size_t i = (size_t)consumed; buf[i] != '\0'; i++) {
    if (!isspace((unsigned char)buf[i])) return false;
  }
  if (pid <= 1 || pid > INT_MAX || display_id == 0) return false;

  out->pid = (pid_t)pid;
  out->display_id = (CGDirectDisplayID)display_id;
  out->x = x;
  out->y = y;
  return true;
}

static bool write_state(const char *state_path, const DisplayState *state) {
  char tmp_path[PATH_MAX];
  int n = snprintf(tmp_path, sizeof(tmp_path), "%s.tmp.%lld", state_path, (long long)getpid());
  if (n <= 0 || (size_t)n >= sizeof(tmp_path)) return false;

  int fd = open(tmp_path, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0600);
  if (fd < 0) {
    fprintf(stderr, "hidden-display: cannot write %s: %s\n", tmp_path, strerror(errno));
    return false;
  }
  FILE *f = fdopen(fd, "w");
  if (f == NULL) {
    close(fd);
    unlink(tmp_path);
    return false;
  }
  bool ok = fprintf(f, "pid=%lld\ndisplay=%u\norigin=%d,%d\n",
                    (long long)state->pid, state->display_id, state->x, state->y) > 0;
  if (fclose(f) != 0) ok = false;
  if (!ok || rename(tmp_path, state_path) != 0) {
    fprintf(stderr, "hidden-display: could not save %s: %s\n", state_path, strerror(errno));
    unlink(tmp_path);
    return false;
  }
  return true;
}

// Confirms `pid` is a live `hidden-display --daemon` process owned by this
// user, so a recycled PID (even for another `hidden-display` CLI invocation) is
// never reused or signalled.
static bool is_daemon_process(pid_t pid) {
  if (pid <= 1 || pid == getpid()) return false;
  struct proc_bsdinfo info;
  if (proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, (int)sizeof(info)) != (int)sizeof(info)) {
    return false;
  }
  if (info.pbi_status == SZOMB || info.pbi_uid != getuid()) return false;
  if (strcmp(info.pbi_comm, PROC_NAME) != 0 && strcmp(info.pbi_name, PROC_NAME) != 0) {
    return false;
  }

  int mib[3] = {CTL_KERN, KERN_PROCARGS2, pid};
  size_t size = 0;
  if (sysctl(mib, 3, NULL, &size, NULL, 0) != 0 || size <= sizeof(int)) return false;
  char *buf = malloc(size);
  if (buf == NULL) return false;
  bool is_daemon = false;
  if (sysctl(mib, 3, buf, &size, NULL, 0) == 0 && size > sizeof(int)) {
    int argc = 0;
    memcpy(&argc, buf, sizeof(argc));
    if (argc == 2) {
      char *p = buf + sizeof(argc);
      char *end = buf + size;
      // Skip exec_path and trailing NUL padding to reach argv[0], then argv[1].
      while (p < end && *p != '\0') p++;
      while (p < end && *p == '\0') p++;
      while (p < end && *p != '\0') p++;
      if (p < end) p++;
      static const char kDaemonArg[] = "--daemon";
      if ((size_t)(end - p) >= sizeof(kDaemonArg) &&
          memcmp(p, kDaemonArg, sizeof(kDaemonArg)) == 0) {
        is_daemon = true;
      }
    }
  }
  free(buf);
  return is_daemon;
}

// Computes the far bottom-right corner past every active display except `skip`.
static void far_corner_origin(CGDirectDisplayID skip, int *out_x, int *out_y) {
  int x = 0, y = 0;
  uint32_t count = 0;
  if (CGGetActiveDisplayList(0, NULL, &count) == kCGErrorSuccess && count > 0) {
    CGDirectDisplayID *others = calloc(count, sizeof(CGDirectDisplayID));
    uint32_t got = 0;
    if (others != NULL && CGGetActiveDisplayList(count, others, &got) == kCGErrorSuccess) {
      for (uint32_t i = 0; i < got; i++) {
        if (others[i] == skip) continue;
        CGRect bounds = CGDisplayBounds(others[i]);
        x = MAX(x, (int)(bounds.origin.x + bounds.size.width));
        y = MAX(y, (int)(bounds.origin.y + bounds.size.height));
      }
    }
    free(others);
  }
  *out_x = x;
  *out_y = y;
}

static bool display_is_live(CGDirectDisplayID target, pid_t owner_pid, int *out_x, int *out_y) {
  uint32_t count = 0;
  if (CGGetActiveDisplayList(0, NULL, &count) != kCGErrorSuccess || count == 0) {
    return false;
  }
  CGDirectDisplayID *displays = calloc(count, sizeof(CGDirectDisplayID));
  if (displays == NULL) return false;

  bool found = false;
  uint32_t got = 0;
  if (CGGetActiveDisplayList(count, displays, &got) == kCGErrorSuccess) {
    for (uint32_t i = 0; i < got; i++) {
      if (displays[i] == target) {
        if (CGDisplayVendorNumber(target) == VENDOR_ID &&
            CGDisplayModelNumber(target) == PRODUCT_ID &&
            CGDisplaySerialNumber(target) == (uint32_t)owner_pid) {
          CGRect bounds = CGDisplayBounds(target);
          *out_x = (int)bounds.origin.x;
          *out_y = (int)bounds.origin.y;
          found = true;
        }
        break;
      }
    }
  }
  free(displays);
  return found;
}

static bool stop_process(pid_t pid) {
  if (!is_daemon_process(pid)) return true;
  if (kill(pid, SIGTERM) != 0) {
    return errno == ESRCH;
  }
  for (int i = 0; i < 200; i++) {
    if (!is_daemon_process(pid)) return true;
    usleep(25000);
  }
  if (is_daemon_process(pid)) {
    (void)kill(pid, SIGKILL);
    for (int i = 0; i < 40; i++) {
      if (!is_daemon_process(pid)) return true;
      usleep(25000);
    }
  }
  return !is_daemon_process(pid);
}

static uint64_t monotonic_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u;
}

static bool spawn_daemon(DisplayState *out) {
  char exe[PATH_MAX];
  uint32_t exe_size = sizeof(exe);
  if (_NSGetExecutablePath(exe, &exe_size) != 0) {
    fprintf(stderr, "hidden-display: could not locate executable\n");
    return false;
  }

  int ready_pipe[2];
  if (pipe(ready_pipe) != 0) {
    fprintf(stderr, "hidden-display: pipe failed: %s\n", strerror(errno));
    return false;
  }

  // The daemon inherits stderr only until it redirects stderr then stdout to
  // /dev/null after printing readiness, so startup errors reach the caller
  // without holding any pipe open once it detaches.
  posix_spawn_file_actions_t actions;
  posix_spawn_file_actions_init(&actions);
  posix_spawn_file_actions_addopen(&actions, STDIN_FILENO, "/dev/null", O_RDONLY, 0);
  posix_spawn_file_actions_adddup2(&actions, ready_pipe[1], STDOUT_FILENO);
  posix_spawn_file_actions_addinherit_np(&actions, STDERR_FILENO);

  posix_spawnattr_t attr;
  posix_spawnattr_init(&attr);
  posix_spawnattr_setflags(&attr, POSIX_SPAWN_SETSID | POSIX_SPAWN_CLOEXEC_DEFAULT);

  char *argv[] = {exe, "--daemon", NULL};
  pid_t child_pid = -1;
  int rc = posix_spawn(&child_pid, exe, &actions, &attr, argv, environ);
  posix_spawn_file_actions_destroy(&actions);
  posix_spawnattr_destroy(&attr);
  close(ready_pipe[1]);

  if (rc != 0) {
    fprintf(stderr, "hidden-display: could not spawn daemon: %s\n", strerror(rc));
    close(ready_pipe[0]);
    return false;
  }

  char buf[256];
  size_t len = 0;
  buf[0] = '\0';
  uint64_t deadline = monotonic_ms() + 10000u;

  // Read until EOF so we know the daemon has detached both stderr and stdout.
  while (len < sizeof(buf) - 1) {
    uint64_t now = monotonic_ms();
    if (now >= deadline) break;
    struct pollfd pfd = {.fd = ready_pipe[0], .events = POLLIN};
    int pr = poll(&pfd, 1, (int)(deadline - now));
    if (pr < 0) {
      if (errno == EINTR) continue;
      break;
    }
    if (pr == 0) break;
    ssize_t n = read(ready_pipe[0], buf + len, sizeof(buf) - 1 - len);
    if (n > 0) {
      len += (size_t)n;
      buf[len] = '\0';
    } else if (n == 0 || errno != EINTR) {
      break;
    }
  }
  close(ready_pipe[0]);

  unsigned int display_id = 0;
  int x = 0, y = 0;
  if (sscanf(buf, "ready %u %d %d", &display_id, &x, &y) == 3 && display_id > 0) {
    out->pid = child_pid;
    out->display_id = (CGDirectDisplayID)display_id;
    out->x = x;
    out->y = y;
    return true;
  }

  fprintf(stderr, "hidden-display: display daemon did not become ready\n");
  (void)stop_process(child_pid);
  (void)waitpid(child_pid, NULL, WNOHANG);
  return false;
}

static int run_daemon(void) {
  signal(SIGHUP, SIG_IGN);
  // Do not hold the caller's working directory open across long-lived runs.
  (void)chdir("/");
  @autoreleasepool {
    CGVirtualDisplayDescriptor *descriptor = [CGVirtualDisplayDescriptor new];
    descriptor.queue = dispatch_get_main_queue();
    descriptor.name = @"Hidden Display";
    // Room for twice the mode in pixels, or the system offers no mode at
    // twice the density of the largest.
    descriptor.maxPixelsWide = WIDE * 4;
    descriptor.maxPixelsHigh = HIGH * 4;
    descriptor.sizeInMillimeters = CGSizeMake(WIDE * 0.2, HIGH * 0.2);
    descriptor.productID = PRODUCT_ID;
    descriptor.vendorID = VENDOR_ID;
    descriptor.serialNum = (unsigned int)getpid();
    CGVirtualDisplay *display = [[CGVirtualDisplay alloc] initWithDescriptor:descriptor];
    if (display == nil) {
      fprintf(stderr, "hidden-display: the display could not be made\n");
      return 1;
    }
    CGVirtualDisplaySettings *settings = [CGVirtualDisplaySettings new];
    settings.hiDPI = 1;
    settings.modes = @[ [[CGVirtualDisplayMode alloc] initWithWidth:WIDE height:HIGH refreshRate:120] ];
    if (![display applySettings:settings]) {
      fprintf(stderr, "hidden-display: the display's mode could not be set\n");
      return 1;
    }
    CGDirectDisplayID number = display.displayID;
    // Off the far bottom-right corner of all active displays, touching only at
    // that corner so the pointer does not wander onto it.
    int x = 0, y = 0;
    far_corner_origin(number, &x, &y);

    // Points at twice the pixels, as on a Retina screen.
    CGDisplayModeRef retina = NULL;
    NSDictionary *all = @{(__bridge NSString *)kCGDisplayShowDuplicateLowResolutionModes : @YES};
    NSArray *modes = CFBridgingRelease(CGDisplayCopyAllDisplayModes(number, (__bridge CFDictionaryRef)all));
    for (id each in modes) {
      CGDisplayModeRef mode = (__bridge CGDisplayModeRef)each;
      if (CGDisplayModeGetWidth(mode) == WIDE && CGDisplayModeGetPixelWidth(mode) == WIDE * 2) {
        retina = mode;
      }
    }
    CGDisplayConfigRef config;
    if (CGBeginDisplayConfiguration(&config) == kCGErrorSuccess) {
      if (retina != NULL) {
        CGConfigureDisplayWithDisplayMode(config, number, retina, NULL);
      }
      CGConfigureDisplayOrigin(config, number, x, y);
      CGCompleteDisplayConfiguration(config, kCGConfigureForSession);
    }

    // Install clean signal handlers before reporting readiness.
    signal(SIGTERM, SIG_IGN);
    signal(SIGINT, SIG_IGN);
    __block CGVirtualDisplay *held = display;
    dispatch_source_t term = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
    dispatch_source_t intr = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
    dispatch_block_t shutdown = ^{
      held = nil;
      exit(0);
    };
    dispatch_source_set_event_handler(term, shutdown);
    dispatch_source_set_event_handler(intr, shutdown);
    dispatch_resume(term);
    dispatch_resume(intr);

    CGRect at = CGDisplayBounds(number);
    printf("ready %u %d %d\n", number, (int)at.origin.x, (int)at.origin.y);
    fflush(stdout);

    // Detach stderr first, then stdout, so EOF on the readiness pipe means no
    // caller-owned pipe stays open in the daemon.
    int devnull = open("/dev/null", O_RDWR);
    if (devnull >= 0) {
      dup2(devnull, STDERR_FILENO);
      dup2(devnull, STDOUT_FILENO);
      if (devnull > STDERR_FILENO) close(devnull);
    }
    dispatch_main();
  }
}

static int cmd_ensure(const char *state_path, const char *lock_path) {
  int lock_fd = open_and_lock(lock_path, LOCK_EX);
  if (lock_fd < 0) return 1;

  DisplayState state;
  if (read_state(state_path, &state)) {
    if (is_daemon_process(state.pid)) {
      int live_x = state.x, live_y = state.y;
      if (display_is_live(state.display_id, state.pid, &live_x, &live_y)) {
        // If screens grew or rearranged since startup, push the virtual display
        // back past the far corner so the pointer cannot wander onto it.
        int want_x = 0, want_y = 0;
        far_corner_origin(state.display_id, &want_x, &want_y);
        if (live_x < want_x || live_y < want_y) {
          CGDisplayConfigRef config;
          if (CGBeginDisplayConfiguration(&config) == kCGErrorSuccess) {
            CGConfigureDisplayOrigin(config, state.display_id, want_x, want_y);
            CGCompleteDisplayConfiguration(config, kCGConfigureForSession);
          }
          CGRect at = CGDisplayBounds(state.display_id);
          live_x = (int)at.origin.x;
          live_y = (int)at.origin.y;
        }
        if (live_x != state.x || live_y != state.y) {
          state.x = live_x;
          state.y = live_y;
          (void)write_state(state_path, &state);
        }
        printf("%u %d %d\n", state.display_id, state.x, state.y);
        fflush(stdout);
        close(lock_fd);
        return 0;
      }
      // The daemon is still around but its display is gone: stop it first.
      (void)stop_process(state.pid);
    }
    (void)unlink(state_path);
  }

  if (!spawn_daemon(&state)) {
    close(lock_fd);
    return 1;
  }
  if (!write_state(state_path, &state)) {
    (void)stop_process(state.pid);
    close(lock_fd);
    return 1;
  }

  printf("%u %d %d\n", state.display_id, state.x, state.y);
  fflush(stdout);
  close(lock_fd);
  return 0;
}

static int cmd_status(const char *state_path, const char *lock_path) {
  int lock_fd = open_and_lock(lock_path, LOCK_SH);
  if (lock_fd < 0) return 1;

  DisplayState state;
  if (read_state(state_path, &state) && is_daemon_process(state.pid)) {
    int live_x = state.x, live_y = state.y;
    if (display_is_live(state.display_id, state.pid, &live_x, &live_y)) {
      printf("%u %d %d (pid %lld)\n", state.display_id, live_x, live_y,
             (long long)state.pid);
      fflush(stdout);
      close(lock_fd);
      return 0;
    }
  }

  printf("hidden-display: not running\n");
  fflush(stdout);
  close(lock_fd);
  return 1;
}

static int cmd_stop(const char *state_path, const char *lock_path) {
  int lock_fd = open_and_lock(lock_path, LOCK_EX);
  if (lock_fd < 0) return 1;

  DisplayState state;
  bool had_live = false;
  if (read_state(state_path, &state) && is_daemon_process(state.pid)) {
    had_live = true;
    if (!stop_process(state.pid)) {
      fprintf(stderr, "hidden-display: could not stop pid %lld\n", (long long)state.pid);
      close(lock_fd);
      return 1;
    }
  }
  (void)unlink(state_path);

  if (had_live) {
    printf("hidden-display: stopped (pid %lld, display %u)\n", (long long)state.pid,
           state.display_id);
  } else {
    printf("hidden-display: not running\n");
  }
  fflush(stdout);
  close(lock_fd);
  return 0;
}

static void print_usage(FILE *stream) {
  fprintf(stream, "usage: hidden-display ensure | status | stop\n");
}

int main(int argc, char **argv) {
  if (argc == 2 && strcmp(argv[1], "--daemon") == 0) {
    return run_daemon();
  }
  if (argc == 2 && (strcmp(argv[1], "-h") == 0 || strcmp(argv[1], "--help") == 0)) {
    print_usage(stdout);
    return 0;
  }

  char state_path[PATH_MAX];
  char lock_path[PATH_MAX];
  if (!resolve_paths(state_path, sizeof(state_path), lock_path, sizeof(lock_path))) {
    fprintf(stderr, "hidden-display: could not resolve state path\n");
    return 1;
  }

  if (argc == 2 && strcmp(argv[1], "ensure") == 0) {
    return cmd_ensure(state_path, lock_path);
  }
  if (argc == 2 && strcmp(argv[1], "status") == 0) {
    return cmd_status(state_path, lock_path);
  }
  if (argc == 2 && strcmp(argv[1], "stop") == 0) {
    return cmd_stop(state_path, lock_path);
  }

  print_usage(stderr);
  return 2;
}
