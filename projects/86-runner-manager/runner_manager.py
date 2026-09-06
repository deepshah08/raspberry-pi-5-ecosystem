import argparse
import json
import logging
import os
import requests
import docker
import sys
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GitHubClient:
    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{repo}/actions/runners"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def list_runners(self) -> List[Dict[str, Any]]:
        try:
            response = requests.get(self.base_url, headers=self.headers)
            response.raise_for_status()
            return response.json().get('runners', [])
        except requests.RequestException as e:
            logger.error(f"Error fetching runners from GitHub: {e}")
            return []

    def remove_runner(self, runner_id: int) -> bool:
        try:
            url = f"{self.base_url}/{runner_id}"
            response = requests.delete(url, headers=self.headers)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"Error removing runner {runner_id} from GitHub: {e}")
            return False

    def get_registration_token(self) -> Optional[str]:
        try:
            url = f"https://api.github.com/repos/{self.repo}/actions/runners/registration-token"
            response = requests.post(url, headers=self.headers)
            response.raise_for_status()
            return response.json().get('token')
        except requests.RequestException as e:
            logger.error(f"Error getting registration token: {e}")
            return None


class DockerClient:
    def __init__(self):
        try:
            self.client = docker.from_env()
        except docker.errors.DockerException as e:
            logger.error(f"Could not connect to Docker daemon: {e}")
            self.client = None

    def list_runner_containers(self) -> List[Any]:
        if not self.client:
            return []
        try:
            # We look for containers with label gh-runner or name matching something
            # Based on requirements: "Docker containers tagged gh-runner"
            # It could mean the image is tagged gh-runner, or it has a label. Let's use a label for robustness, or image name.
            # Assuming 'gh-runner' is part of the image name or a label
            containers = self.client.containers.list(all=True, filters={"label": "gh-runner=true"})

            # If nothing returned, let's also check if the image has 'gh-runner' in it, or name
            if not containers:
                containers = self.client.containers.list(all=True)
                return [c for c in containers if 'gh-runner' in c.image.tags or 'gh-runner' in c.name or c.labels.get('gh-runner') == 'true']

            return containers
        except Exception as e:
            logger.error(f"Error listing Docker containers: {e}")
            return []

    def remove_container(self, container_id: str) -> bool:
        if not self.client:
            return False
        try:
            container = self.client.containers.get(container_id)
            container.remove(force=True)
            return True
        except Exception as e:
            logger.error(f"Error removing container {container_id}: {e}")
            return False

    def start_runner(self, repo: str, token: str, name: str) -> bool:
        if not self.client:
            return False
        try:
            self.client.containers.run(
                image="gh-runner:latest",  # Assuming local image
                name=name,
                detach=True,
                labels={"gh-runner": "true"},
                environment={
                    "REPO_URL": f"https://github.com/{repo}",
                    "RUNNER_TOKEN": token,
                    "RUNNER_NAME": name,
                    "EPHEMERAL": "1"
                },
                mem_limit="1G",
                cpu_quota=50000 # CPUQuota=50%
            )
            return True
        except Exception as e:
            logger.error(f"Error starting runner container {name}: {e}")
            return False


class RunnerManager:
    def __init__(self, github_client: GitHubClient, docker_client: DockerClient, max_runners: int, dry_run: bool):
        self.github = github_client
        self.docker = docker_client
        self.max_runners = max_runners
        self.dry_run = dry_run

    def audit(self) -> Dict[str, Any]:
        logger.info("Starting audit...")
        report = {
            "github_runners": [],
            "docker_containers": [],
            "actions_taken": []
        }

        # 1. Check GitHub runners
        gh_runners = self.github.list_runners()
        report["github_runners"] = [r['name'] for r in gh_runners]

        # 2. Check Docker containers
        containers = self.docker.list_runner_containers()
        report["docker_containers"] = [c.name for c in containers]

        active_runner_names = [r['name'] for r in gh_runners if r['status'] == 'online']
        offline_runners = [r for r in gh_runners if r['status'] == 'offline']

        # Clean up offline runners from GitHub
        for runner in offline_runners:
            msg = f"Found offline runner in GitHub: {runner['name']} (ID: {runner['id']})"
            logger.info(msg)
            if not self.dry_run:
                if self.github.remove_runner(runner['id']):
                    report["actions_taken"].append(f"Removed offline GitHub runner: {runner['name']}")
            else:
                report["actions_taken"].append(f"[DRY-RUN] Would remove offline GitHub runner: {runner['name']}")

        # Clean up dead/hung containers
        for c in containers:
            # If container exited, or if it's running but not registered in GitHub as online
            if c.status == 'exited' or c.status == 'dead':
                msg = f"Found dead/exited container: {c.name}"
                logger.info(msg)
                if not self.dry_run:
                    if self.docker.remove_container(c.id):
                        report["actions_taken"].append(f"Removed dead container: {c.name}")
                else:
                    report["actions_taken"].append(f"[DRY-RUN] Would remove dead container: {c.name}")

            # Check high memory usage (just mock logic for now since getting stats can be slow)
            # In a real app we might do c.stats(stream=False)
            try:
                if c.status == 'running':
                    stats = c.stats(stream=False)
                    mem_usage = stats.get('memory_stats', {}).get('usage', 0)
                    # 1G = 1024 * 1024 * 1024 bytes
                    if mem_usage > 1 * 1024 * 1024 * 1024:
                        msg = f"Container {c.name} exceeding memory limits."
                        logger.warning(msg)
                        if not self.dry_run:
                            if self.docker.remove_container(c.id):
                                report["actions_taken"].append(f"Removed high-memory container: {c.name}")
                        else:
                            report["actions_taken"].append(f"[DRY-RUN] Would remove high-memory container: {c.name}")
            except Exception as e:
                logger.debug(f"Could not get stats for {c.name}: {e}")

        return report

    def scale(self) -> Dict[str, Any]:
        logger.info("Starting scale...")
        report = {"actions_taken": []}

        gh_runners = self.github.list_runners()
        active_runners = [r for r in gh_runners if r['status'] == 'online']

        # Determine how many we need
        current_count = len(active_runners)
        needed = self.max_runners - current_count

        if needed > 0:
            logger.info(f"Need {needed} more runners (Current: {current_count}, Max: {self.max_runners})")
            token = self.github.get_registration_token() if not self.dry_run else "mock-token"

            if token or self.dry_run:
                for i in range(needed):
                    timestamp = int(datetime.now(timezone.utc).timestamp())
                    new_name = f"gh-runner-{timestamp}-{i}"

                    if not self.dry_run:
                        if self.docker.start_runner(self.github.repo, token, new_name):
                            report["actions_taken"].append(f"Started new runner container: {new_name}")
                    else:
                        report["actions_taken"].append(f"[DRY-RUN] Would start new runner container: {new_name}")
            else:
                logger.error("Failed to get registration token, cannot scale up.")
        elif needed < 0:
            logger.info(f"Have excess runners (Current: {current_count}, Max: {self.max_runners}). Note: Ephemeral runners will scale down naturally.")
        else:
            logger.info("Runner count is at desired capacity.")

        return report

def main():
    parser = argparse.ArgumentParser(description="Automated Homelab GitHub Actions Self-Hosted Runner Manager")
    parser.add_argument("--audit-now", action="store_true", help="Audit Docker containers and GitHub runners")
    parser.add_argument("--repo", type=str, required=True, help="GitHub repository (owner/repo)")
    parser.add_argument("--max-runners", type=int, default=3, help="Maximum number of active runners")
    parser.add_argument("--dry-run", action="store_true", help="Do not make any actual changes")
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN", "")

    github_client = GitHubClient(token, args.repo)
    docker_client = DockerClient()

    manager = RunnerManager(github_client, docker_client, args.max_runners, args.dry_run)

    report = {}

    if args.audit_now:
        report["audit"] = manager.audit()

    report["scale"] = manager.scale()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for action in report.get("audit", {}).get("actions_taken", []):
            print(f"AUDIT: {action}")
        for action in report.get("scale", {}).get("actions_taken", []):
            print(f"SCALE: {action}")

if __name__ == "__main__":
    main()
