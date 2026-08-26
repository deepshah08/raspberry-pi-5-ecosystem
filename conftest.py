import os
import sys

# Ensure root directory is on sys.path
root_dir = os.path.dirname(os.path.abspath(__file__))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Add scripts/ directory to sys.path
scripts_dir = os.path.join(root_dir, 'scripts')
if os.path.isdir(scripts_dir) and scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

# Automatically add all projects/* directories to sys.path for test resolution
projects_dir = os.path.join(root_dir, 'projects')
if os.path.isdir(projects_dir):
    for entry in sorted(os.listdir(projects_dir)):
        project_path = os.path.join(projects_dir, entry)
        if os.path.isdir(project_path) and project_path not in sys.path:
            sys.path.insert(0, project_path)
            # If project has a config or scripts subdirectory, add it as well
            for sub in ['config', 'scripts']:
                sub_path = os.path.join(project_path, sub)
                if os.path.isdir(sub_path) and sub_path not in sys.path:
                    sys.path.insert(0, sub_path)
