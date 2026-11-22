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
// placed past the far bottom-right corner of the furthest online display so the
// pointer does not wander onto it.
//
// clang -Wall -Wextra -fobjc-arc -framework Foundation -framework CoreGraphics \
//   hidden-display.m -o hidden-display

#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
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

static bool using_override_dir(void) {
  const char *override = getenv(STATE_DIR_ENV);
  return override != NULL && override[0] != '\0';
}

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

static bool parse_strict_ll(const char *s, const char **end_out, long long *val_out) {
  if (*s != '-' && (*s < '0' || *s > '9')) return false;
  if (*s == '-' && (s[1] < '0' || s[1] > '9')) return false;
  errno = 0;
  char *end = NULL;
  long long v = strtoll(s, &end, 10);
  if (errno != 0 || end == s) return false;
  *end_out = end;
  *val_out = v;
  return true;
}

static bool parse_strict_u32(const char *s, const char **end_out, uint32_t *val_out) {
  if (*s < '0' || *s > '9') return false;
  errno = 0;
  char *end = NULL;
  unsigned long v = strtoul(s, &end, 10);
  if (errno != 0 || end == s || v > UINT32_MAX) return false;
  *end_out = end;
  *val_out = (uint32_t)v;
  return true;
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

  const char *p = buf;
  long long pid = 0, x = 0, y = 0;
  uint32_t display_id = 0;

  if (strncmp(p, "pid=", 4) != 0) return false;
  p += 4;
  if (!parse_strict_ll(p, &p, &pid) || *p != '\n') return false;
  p++;

  if (strncmp(p, "display=", 8) != 0) return false;
  p += 8;
  if (!parse_strict_u32(p, &p, &display_id) || *p != '\n') return false;
  p++;

  if (strncmp(p, "origin=", 7) != 0) return false;
  p += 7;
  if (!parse_strict_ll(p, &p, &x) || *p != ',') return false;
  p++;
  if (!parse_strict_ll(p, &p, &y)) return false;
  if (*p == '\n') p++;
  if (*p != '\0') return false;

  if (pid <= 1 || pid > INT_MAX || display_id == 0) return false;
  if (x < INT_MIN || x > INT_MAX || y < INT_MIN || y > INT_MAX) return false;

  out->pid = (pid_t)pid;
  out->display_id = (CGDirectDisplayID)display_id;
  out->x = (int)x;
  out->y = (int)y;
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
// never reused or signalled. Daemons started with HIDDEN_DISPLAY_STATE_DIR pass
// `--isolated` as argv[2] so default-namespace recovery ignores them.
static bool is_daemon_process_filtered(pid_t pid, bool include_isolated) {
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
    if (argc == 2 || (include_isolated && argc == 3)) {
      char *p = buf + sizeof(argc);
      char *end = buf + size;
      // Skip exec_path and trailing NUL padding to reach argv[0], then argv[1].
      while (p < end && *p != '\0') p++;
      while (p < end && *p == '\0') p++;
      while (p < end && *p != '\0') p++;
      if (p < end) p++;
      static const char kDaemonArg[] = "--daemon";
      static const char kIsolatedArg[] = "--isolated";
      if ((size_t)(end - p) >= sizeof(kDaemonArg) &&
          memcmp(p, kDaemonArg, sizeof(kDaemonArg)) == 0) {
        if (argc == 2) {
          is_daemon = true;
        } else {
          p += sizeof(kDaemonArg);
          if ((size_t)(end - p) >= sizeof(kIsolatedArg) &&
              memcmp(p, kIsolatedArg, sizeof(kIsolatedArg)) == 0) {
            is_daemon = true;
          }
        }
      }
    }
  }
  free(buf);
  return is_daemon;
}

static bool is_daemon_process(pid_t pid) {
  return is_daemon_process_filtered(pid, true);
}

// Finds any live default-namespace `hidden-display --daemon` processes owned by
// this user (excluding `--isolated` test daemons). Used only when the default
// state path is active to recover if the state file was lost while a daemon
// still runs.
static size_t find_daemon_pids(pid_t *out, size_t max_out) {
  int bytes = proc_listpids(PROC_ALL_PIDS, 0, NULL, 0);
  if (bytes <= 0) return 0;
  // Pad slightly for processes spawned between sizing and listing.
  size_t cap = (size_t)bytes / sizeof(pid_t) + 64;
  pid_t *pids = calloc(cap, sizeof(pid_t));
  if (pids == NULL) return 0;
  int got_bytes = proc_listpids(PROC_ALL_PIDS, 0, pids, (int)(cap * sizeof(pid_t)));
  size_t found = 0;
  if (got_bytes > 0) {
    size_t count = (size_t)got_bytes / sizeof(pid_t);
    for (size_t i = 0; i < count && found < max_out; i++) {
      if (pids[i] > 1 && is_daemon_process_filtered(pids[i], false)) {
        out[found++] = pids[i];
      }
    }
  }
  free(pids);
  return found;
}

typedef enum {
  DISPLAY_QUERY_ABSENT = 0,
  DISPLAY_QUERY_FOUND = 1,
  DISPLAY_QUERY_ERROR = -1,
} DisplayQueryStatus;

// Queries all online displays into a newly allocated array (caller frees).
// Returns false if CoreGraphics cannot enumerate displays or allocation fails.
static bool get_online_displays(CGDirectDisplayID **out_displays, uint32_t *out_count) {
  *out_displays = NULL;
  *out_count = 0;
  uint32_t count = 0;
  if (CGGetOnlineDisplayList(0, NULL, &count) != kCGErrorSuccess) {
    return false;
  }
  if (count == 0) {
    return true;
  }
  CGDirectDisplayID *list = calloc(count, sizeof(CGDirectDisplayID));
  if (list == NULL) {
    return false;
  }
  uint32_t got = 0;
  if (CGGetOnlineDisplayList(count, list, &got) != kCGErrorSuccess) {
    free(list);
    return false;
  }
  *out_displays = list;
  *out_count = got;
  return true;
}

// Picks the bottom-right corner of the single online display (excluding `skip`)
// extending furthest right (breaking ties by furthest down). Choosing one real
// display's corner ensures the target point always touches an existing monitor
// on multi-monitor setups instead of floating in empty space. Uses online
// displays so sleeping monitors are still accounted for.
static DisplayQueryStatus far_corner_origin(CGDirectDisplayID skip, int *out_x, int *out_y) {
  CGDirectDisplayID *others = NULL;
  uint32_t got = 0;
  if (!get_online_displays(&others, &got)) {
    return DISPLAY_QUERY_ERROR;
  }
  bool found = false;
  int best_x = 0, best_y = 0;
  for (uint32_t i = 0; i < got; i++) {
    if (others[i] == skip) continue;
    CGRect bounds = CGDisplayBounds(others[i]);
    int right = (int)(bounds.origin.x + bounds.size.width);
    int bottom = (int)(bounds.origin.y + bounds.size.height);
    if (!found || right > best_x || (right == best_x && bottom > best_y)) {
      best_x = right;
      best_y = bottom;
      found = true;
    }
  }
  free(others);
  *out_x = best_x;
  *out_y = best_y;
  return found ? DISPLAY_QUERY_FOUND : DISPLAY_QUERY_ABSENT;
}

// Returns DISPLAY_QUERY_FOUND when `target` overlaps another online display or
// sits inside the bounding extent of another display, DISPLAY_QUERY_ABSENT when
// placement is verified safe, or DISPLAY_QUERY_ERROR if displays cannot be
// enumerated.
static DisplayQueryStatus display_needs_reposition(CGDirectDisplayID target) {
  CGDirectDisplayID *others = NULL;
  uint32_t got = 0;
  if (!get_online_displays(&others, &got)) {
    return DISPLAY_QUERY_ERROR;
  }
  CGRect self_bounds = CGDisplayBounds(target);
  int live_x = (int)self_bounds.origin.x;
  int live_y = (int)self_bounds.origin.y;
  bool needs_move = false;
  for (uint32_t i = 0; i < got; i++) {
    if (others[i] == target) continue;
    CGRect ob = CGDisplayBounds(others[i]);
    CGRect inter = CGRectIntersection(self_bounds, ob);
    if (!CGRectIsNull(inter) && inter.size.width > 0.0 && inter.size.height > 0.0) {
      needs_move = true;
      break;
    }
    int other_right = (int)(ob.origin.x + ob.size.width);
    int other_bottom = (int)(ob.origin.y + ob.size.height);
    if (other_right > live_x && other_bottom > live_y) {
      needs_move = true;
      break;
    }
  }
  free(others);
  return needs_move ? DISPLAY_QUERY_FOUND : DISPLAY_QUERY_ABSENT;
}

static DisplayQueryStatus display_is_live(CGDirectDisplayID target, pid_t owner_pid, int *out_x,
                                          int *out_y) {
  CGDirectDisplayID *displays = NULL;
  uint32_t got = 0;
  if (!get_online_displays(&displays, &got)) {
    return DISPLAY_QUERY_ERROR;
  }
  bool found = false;
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
  free(displays);
  return found ? DISPLAY_QUERY_FOUND : DISPLAY_QUERY_ABSENT;
}

static DisplayQueryStatus find_live_display_for_pid(pid_t owner_pid, DisplayState *out) {
  CGDirectDisplayID *displays = NULL;
  uint32_t got = 0;
  if (!get_online_displays(&displays, &got)) {
    return DISPLAY_QUERY_ERROR;
  }
  bool found = false;
  for (uint32_t i = 0; i < got; i++) {
    CGDirectDisplayID id = displays[i];
    if (CGDisplayVendorNumber(id) == VENDOR_ID &&
        CGDisplayModelNumber(id) == PRODUCT_ID &&
        CGDisplaySerialNumber(id) == (uint32_t)owner_pid) {
      CGRect bounds = CGDisplayBounds(id);
      out->pid = owner_pid;
      out->display_id = id;
      out->x = (int)bounds.origin.x;
      out->y = (int)bounds.origin.y;
      found = true;
      break;
    }
  }
  free(displays);
  return found ? DISPLAY_QUERY_FOUND : DISPLAY_QUERY_ABSENT;
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

  char *argv[] = {exe, "--daemon", using_override_dir() ? "--isolated" : NULL, NULL};
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
    __block CGVirtualDisplay *display = [[CGVirtualDisplay alloc] initWithDescriptor:descriptor];
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
    // Place off the far bottom-right corner of the furthest online display so
    // the pointer does not wander onto it. Never move to (0,0) when no other
    // online display is reported, to avoid claiming the main display.
    int x = 0, y = 0;
    DisplayQueryStatus corner = far_corner_origin(number, &x, &y);
    if (corner == DISPLAY_QUERY_ERROR) {
      fprintf(stderr, "hidden-display: could not query online displays\n");
      display = nil;
      return 1;
    }
    bool has_other = (corner == DISPLAY_QUERY_FOUND);

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
    if (retina != NULL || has_other) {
      CGDisplayConfigRef config;
      CGError cfg_err = CGBeginDisplayConfiguration(&config);
      if (cfg_err == kCGErrorSuccess) {
        if (retina != NULL) {
          CGConfigureDisplayWithDisplayMode(config, number, retina, NULL);
        }
        if (has_other) {
          CGConfigureDisplayOrigin(config, number, x, y);
        }
        cfg_err = CGCompleteDisplayConfiguration(config, kCGConfigureForSession);
      }
      if (has_other &&
          (cfg_err != kCGErrorSuccess ||
           display_needs_reposition(number) != DISPLAY_QUERY_ABSENT)) {
        fprintf(stderr, "hidden-display: could not place display off-screen (CGError %d)\n",
                (int)cfg_err);
        display = nil;
        return 1;
      }
    }

    // Install clean signal handlers before reporting readiness.
    signal(SIGTERM, SIG_IGN);
    signal(SIGINT, SIG_IGN);
    dispatch_source_t term = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
    dispatch_source_t intr = dispatch_source_create(
        DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
    dispatch_block_t shutdown = ^{
      display = nil;
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

static bool reposition_and_sync_state(const char *state_path, DisplayState *state,
                                      bool force_write) {
  int live_x = state->x, live_y = state->y;
  DisplayQueryStatus pos = display_needs_reposition(state->display_id);
  if (pos == DISPLAY_QUERY_ERROR) {
    fprintf(stderr, "hidden-display: could not query online displays\n");
    return false;
  }
  if (pos == DISPLAY_QUERY_FOUND) {
    int want_x = 0, want_y = 0;
    DisplayQueryStatus corner = far_corner_origin(state->display_id, &want_x, &want_y);
    if (corner == DISPLAY_QUERY_ERROR) {
      fprintf(stderr, "hidden-display: could not query online displays\n");
      return false;
    }
    if (corner == DISPLAY_QUERY_FOUND) {
      CGDisplayConfigRef config;
      CGError cfg_err = CGBeginDisplayConfiguration(&config);
      if (cfg_err == kCGErrorSuccess) {
        CGConfigureDisplayOrigin(config, state->display_id, want_x, want_y);
        cfg_err = CGCompleteDisplayConfiguration(config, kCGConfigureForSession);
      }
      if (cfg_err != kCGErrorSuccess ||
          display_needs_reposition(state->display_id) != DISPLAY_QUERY_ABSENT) {
        fprintf(stderr, "hidden-display: could not reposition display off-screen (CGError %d)\n",
                (int)cfg_err);
        return false;
      }
      CGRect at = CGDisplayBounds(state->display_id);
      live_x = (int)at.origin.x;
      live_y = (int)at.origin.y;
    }
  }
  if (force_write || live_x != state->x || live_y != state->y) {
    state->x = live_x;
    state->y = live_y;
    (void)write_state(state_path, state);
  }
  return true;
}

static int cmd_ensure(const char *state_path, const char *lock_path) {
  int lock_fd = open_and_lock(lock_path, LOCK_EX);
  if (lock_fd < 0) return 1;

  DisplayState state;
  if (read_state(state_path, &state)) {
    if (is_daemon_process(state.pid)) {
      int live_x = state.x, live_y = state.y;
      DisplayQueryStatus live = display_is_live(state.display_id, state.pid, &live_x, &live_y);
      if (live == DISPLAY_QUERY_ERROR) {
        fprintf(stderr, "hidden-display: could not query online displays\n");
        close(lock_fd);
        return 1;
      }
      if (live == DISPLAY_QUERY_FOUND) {
        bool origin_changed = (live_x != state.x || live_y != state.y);
        state.x = live_x;
        state.y = live_y;
        if (!reposition_and_sync_state(state_path, &state, origin_changed)) {
          close(lock_fd);
          return 1;
        }
        printf("%u %d %d\n", state.display_id, state.x, state.y);
        fflush(stdout);
        close(lock_fd);
        return 0;
      }
      // The daemon is still around but its display is gone: stop it first.
      if (!stop_process(state.pid)) {
        fprintf(stderr, "hidden-display: could not stop stale daemon pid %lld\n",
                (long long)state.pid);
        close(lock_fd);
        return 1;
      }
    }
    (void)unlink(state_path);
  }

  // If the state file was lost while a daemon is still alive, adopt it (and
  // stop any extra daemons) instead of spawning a duplicate virtual display.
  if (!using_override_dir()) {
    pid_t orphans[16];
    size_t n_orphans = find_daemon_pids(orphans, 16);
    bool adopted = false;
    DisplayState adopted_state;
    for (size_t i = 0; i < n_orphans; i++) {
      DisplayState candidate;
      DisplayQueryStatus found = find_live_display_for_pid(orphans[i], &candidate);
      if (found == DISPLAY_QUERY_ERROR) {
        fprintf(stderr, "hidden-display: could not query online displays\n");
        close(lock_fd);
        return 1;
      }
      if (!adopted && found == DISPLAY_QUERY_FOUND) {
        adopted_state = candidate;
        adopted = true;
      } else if (!stop_process(orphans[i])) {
        fprintf(stderr, "hidden-display: could not stop orphan daemon pid %lld\n",
                (long long)orphans[i]);
        close(lock_fd);
        return 1;
      }
    }
    if (adopted) {
      if (!reposition_and_sync_state(state_path, &adopted_state, true)) {
        close(lock_fd);
        return 1;
      }
      printf("%u %d %d\n", adopted_state.display_id, adopted_state.x, adopted_state.y);
      fflush(stdout);
      close(lock_fd);
      return 0;
    }
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
    DisplayQueryStatus live = display_is_live(state.display_id, state.pid, &live_x, &live_y);
    if (live == DISPLAY_QUERY_ERROR) {
      fprintf(stderr, "hidden-display: could not query online displays\n");
      close(lock_fd);
      return 1;
    }
    if (live == DISPLAY_QUERY_FOUND) {
      printf("%u %d %d (pid %lld)\n", state.display_id, live_x, live_y,
             (long long)state.pid);
      fflush(stdout);
      close(lock_fd);
      return 0;
    }
  }

  if (!using_override_dir()) {
    pid_t orphans[16];
    size_t n_orphans = find_daemon_pids(orphans, 16);
    for (size_t i = 0; i < n_orphans; i++) {
      DisplayQueryStatus found = find_live_display_for_pid(orphans[i], &state);
      if (found == DISPLAY_QUERY_ERROR) {
        fprintf(stderr, "hidden-display: could not query online displays\n");
        close(lock_fd);
        return 1;
      }
      if (found == DISPLAY_QUERY_FOUND) {
        printf("%u %d %d (pid %lld)\n", state.display_id, state.x, state.y,
               (long long)state.pid);
        fflush(stdout);
        close(lock_fd);
        return 0;
      }
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
  pid_t stopped_pid = 0;
  CGDirectDisplayID stopped_display = 0;

  if (read_state(state_path, &state) && is_daemon_process(state.pid)) {
    had_live = true;
    stopped_pid = state.pid;
    stopped_display = state.display_id;
    if (!stop_process(state.pid)) {
      fprintf(stderr, "hidden-display: could not stop pid %lld\n", (long long)state.pid);
      close(lock_fd);
      return 1;
    }
  }
  (void)unlink(state_path);

  if (!using_override_dir()) {
    pid_t orphans[16];
    size_t n_orphans = find_daemon_pids(orphans, 16);
    for (size_t i = 0; i < n_orphans; i++) {
      DisplayState orphan_state;
      CGDirectDisplayID oid = 0;
      if (find_live_display_for_pid(orphans[i], &orphan_state) == DISPLAY_QUERY_FOUND) {
        oid = orphan_state.display_id;
      }
      if (!stop_process(orphans[i])) {
        fprintf(stderr, "hidden-display: could not stop pid %lld\n", (long long)orphans[i]);
        close(lock_fd);
        return 1;
      }
      if (!had_live) {
        had_live = true;
        stopped_pid = orphans[i];
        stopped_display = oid;
      }
    }
  }

  if (had_live) {
    printf("hidden-display: stopped (pid %lld, display %u)\n", (long long)stopped_pid,
           stopped_display);
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
  if ((argc == 2 && strcmp(argv[1], "--daemon") == 0) ||
      (argc == 3 && strcmp(argv[1], "--daemon") == 0 && strcmp(argv[2], "--isolated") == 0)) {
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
