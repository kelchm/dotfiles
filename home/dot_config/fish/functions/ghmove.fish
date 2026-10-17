function ghmove
  set -l sub_dir $argv[1]  # Optional additional sub-directory
  set -l base_dir ~/Development
  set -l current_dir (pwd)
  set -l git_root_dir (git rev-parse --show-toplevel 2>/dev/null)

  if test -z "$git_root_dir"
      echo "Not inside a git repository."
      return 1
  end

  # Append the optional sub-directory to the base directory if provided
  if test -n "$sub_dir"
      set base_dir $base_dir/$sub_dir
  end

  cd $git_root_dir
  set -l remotes (git remote -v | cut -f2 | cut -d' ' -f1 | uniq)
  set -l proposed_paths

  for remote in $remotes
      set -l repo_path (string replace -r '.*:([^/]+)/(.+)\.git' '$1/$2' $remote)
      set proposed_paths $proposed_paths $base_dir/$repo_path
  end

  switch (count $proposed_paths)
      case 1
          echo "Proposed path: $proposed_paths[1]"
          echo "Confirm move? [Y/n]"
          read -l confirm
          if test $confirm = 'Y' -o $confirm = 'y'
              echo "Moving to $proposed_paths[1]"
              # Move to the parent directory of the proposed path
              set -l parent_dir (dirname $proposed_paths[1])
              mkdir -p $parent_dir
              mv $git_root_dir $parent_dir
          end
      case '*'
          echo "Multiple remotes found. Select a path:"
          for i in (seq (count $proposed_paths))
              echo "$i: $proposed_paths[$i]"
          end
          read -l choice
          set -l selected_path $proposed_paths[$choice]
          if test -n "$selected_path"
              echo "Moving to $selected_path"
              set -l parent_dir (dirname $selected_path)
              mkdir -p $parent_dir
              mv $git_root_dir $parent_dir
          else
              echo "Invalid selection."
          end
  end
end
