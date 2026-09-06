#!/usr/bin/env python3
import subprocess
import urllib.request
import os
import sys

def configure_git_user(name: str, email: str) -> bool:
    """Configures the git user name and email globally."""
    try:
        subprocess.run(["git", "config", "--global", "user.name", name], check=True)
        subprocess.run(["git", "config", "--global", "user.email", email], check=True)
        print(f"Git user configured: {name} <{email}>")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to configure git user: {e}")
        return False

def clone_repository(repo_url: str, dest_dir: str) -> bool:
    """Clones a git repository into the specified directory."""
    if os.path.exists(dest_dir) and os.listdir(dest_dir):
        print(f"Directory {dest_dir} is not empty. Skipping clone.")
        return True
    try:
        subprocess.run(["git", "clone", repo_url, dest_dir], check=True)
        print(f"Successfully cloned {repo_url} to {dest_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to clone repository {repo_url}: {e}")
        return False

def setup_python_venv(venv_dir: str) -> bool:
    """Sets up a Python virtual environment in the specified directory."""
    if os.path.exists(venv_dir):
         print(f"Venv directory {venv_dir} already exists. Skipping setup.")
         return True
    try:
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)
        print(f"Successfully created Python virtual environment at {venv_dir}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to create Python virtual environment at {venv_dir}: {e}")
        return False

def check_connectivity(url: str = "https://github.com", timeout: int = 5) -> bool:
    """Checks network connectivity by attempting to open a URL."""
    try:
        urllib.request.urlopen(url, timeout=timeout)
        print(f"Successfully connected to {url}")
        return True
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"Failed to connect to {url}: {e}")
        return False

def main():
    print("Starting workspace bootstrap process...")
    if not check_connectivity():
        print("Network connectivity check failed. Proceeding with caution.")

    # Example usage (can be modified or configured via environment variables later)
    configure_git_user("Nomad User", "nomad@example.com")

    workspace_dir = os.environ.get("WORKSPACE_DIR", "./workspace")
    os.makedirs(workspace_dir, exist_ok=True)

    # repo_url = "https://github.com/octocat/Hello-World.git"
    # dest = os.path.join(workspace_dir, "Hello-World")
    # clone_repository(repo_url, dest)

    venv_dir = os.environ.get("VENV_DIR", os.path.join(workspace_dir, ".venv"))
    setup_python_venv(venv_dir)
    print("Workspace bootstrap complete.")

if __name__ == "__main__":
    main()
