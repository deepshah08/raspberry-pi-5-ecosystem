import os
import sys
import time
import subprocess
import json
import logging
from worker_config import REPOSITORIES, WORKSPACE_DIR, POLL_INTERVAL_SECONDS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('JulesAgentWorker')

class JulesReviewWorker:
    def __init__(self, repositories=None):
        self.repositories = repositories or REPOSITORIES
        self.workspace = WORKSPACE_DIR

    def fetch_open_prs(self, repo: str) -> list:
        try:
            cmd = ['gh', 'pr', 'list', '--repo', repo, '--json', 'number,title,headRefName,author,url']
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return json.loads(res.stdout)
        except Exception as e:
            logger.debug(f'gh query for {repo}: {e}')
            return []

    def inspect_diff_syntax(self, file_paths: list) -> list:
        import ast
        issues = []
        for path in file_paths:
            if path.endswith('.py') and os.path.exists(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        ast.parse(f.read(), filename=path)
                except SyntaxError as se:
                    issues.append(f'SyntaxError in {path}:{se.lineno}: {se.msg}')
                except Exception as e:
                    issues.append(f'Parse error in {path}: {e}')
        return issues

    def run_tests(self, target_dir: str, test_cmd='pytest -v --tb=short') -> tuple:
        try:
            res = subprocess.run(
                test_cmd,
                shell=True,
                cwd=target_dir,
                capture_output=True,
                text=True,
                timeout=120
            )
            return (res.returncode == 0), res.stdout + res.stderr
        except subprocess.TimeoutExpired:
            return False, 'Test execution timed out after 120 seconds.'
        except Exception as e:
            return False, str(e)

    def generate_review_summary(self, pr_data: dict, test_passed: bool, output_log: str, syntax_issues: list) -> dict:
        pr_number = pr_data.get('number', 'N/A')
        pr_title = pr_data.get('title', 'Unknown')
        
        if test_passed and not syntax_issues:
            verdict = 'APPROVE'
            body = (
                '### ✅ Jules Automated Code Review: LGTM\n\n'
                + f'**PR #{pr_number}**: {pr_title}\n'
                + '- Automated test suite passed successfully on Raspberry Pi 5 ARM64 worker.\n'
                + '- Zero AST/Syntax errors detected.\n\n'
                + 'Ready for merge.'
            )
        else:
            verdict = 'REQUEST_CHANGES'
            issue_list = '\n'.join([f'- {iss}' for iss in syntax_issues])
            log_snippet = output_log[-1000:] if output_log else 'No test output'
            body = (
                '### ⚠️ Jules Automated Code Review: Changes Requested\n\n'
                + f'**PR #{pr_number}**: {pr_title}\n\n'
                + f'#### Issues Detected:\n{issue_list}\n\n'
                + f'#### Test Output Log:\n```text\n{log_snippet}\n```'
            )
            
        return {'verdict': verdict, 'body': body, 'pr_number': pr_number}
