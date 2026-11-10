import os
import sys
import time
import shutil
import tempfile
import subprocess
import re
from typing import Dict
from sentinel.schemas.models import SandboxExecutionResult
from sentinel.config import settings

class SandboxRunner:
    """
    Executes generated reproduction tests against code snapshots in an isolated workspace.
    Enforces process timeouts and captures raw stdout/stderr along with test failure analytics.
    """

    def __init__(self, timeout_seconds: int = None):
        self.timeout_seconds = timeout_seconds or settings.execution_timeout_seconds

    def execute_test_suite(
        self,
        code_files: Dict[str, str],
        test_file_name: str,
        test_file_content: str
    ) -> SandboxExecutionResult:
        """
        Creates an isolated temporary directory, writes target code and test files,
        and invokes pytest via subprocess with strict timeout guards.
        """
        temp_dir = tempfile.mkdtemp(prefix="sentinel_sandbox_")
        start_time = time.time()
        
        try:
            # 1. Write codebase files (with path traversal guard)
            python_paths = [temp_dir]
            abs_temp = os.path.abspath(temp_dir)
            for file_path, content in code_files.items():
                clean_rel = file_path.lstrip("/\\")
                target_path = os.path.abspath(os.path.join(abs_temp, clean_rel))
                if not target_path.startswith(abs_temp + os.sep) and target_path != abs_temp:
                    raise ValueError(f"Unsafe file path outside sandbox: {file_path}")
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as f:
                    f.write(content)
                parent_dir = os.path.dirname(target_path)
                if parent_dir not in python_paths:
                    python_paths.append(parent_dir)

            # 2. Write reproduction test file
            clean_test_rel = test_file_name.lstrip("/\\")
            test_target_path = os.path.abspath(os.path.join(abs_temp, clean_test_rel))
            if not test_target_path.startswith(abs_temp + os.sep):
                raise ValueError(f"Unsafe test path outside sandbox: {test_file_name}")
            os.makedirs(os.path.dirname(test_target_path), exist_ok=True)
            with open(test_target_path, "w", encoding="utf-8") as f:
                f.write(test_file_content)

            # 3. Determine python executable
            python_exe = sys.executable

            # 4. Run pytest inside the isolated workspace
            cmd = [
                python_exe,
                "-m",
                "pytest",
                test_file_name,
                f"--rootdir={temp_dir}",
                "--noconftest",
                "-p",
                "no:cacheprovider",
                "-v",
                "--tb=short",
            ]
            
            # Inject PYTHONPATH so imports resolve correctly in temp_dir and nested packages
            # Disable heavy global pytest plugin autoloading (e.g., deepeval) inside isolated sandbox
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join(python_paths)
            env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"

            process = subprocess.run(
                cmd,
                cwd=temp_dir,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                env=env
            )
            
            elapsed = time.time() - start_time
            stdout = process.stdout
            stderr = process.stderr
            exit_code = process.returncode
            
            # Parse test statistics from stdout
            passed, total, failures, errors = self._parse_pytest_output(stdout, exit_code)
            
            return SandboxExecutionResult(
                passed=passed,
                total_tests=total,
                failures=failures,
                errors=errors,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                execution_time_seconds=round(elapsed, 3)
            )

        except subprocess.TimeoutExpired as exc:
            elapsed = time.time() - start_time
            return SandboxExecutionResult(
                passed=False,
                total_tests=0,
                failures=1,
                errors=1,
                stdout=exc.stdout or "",
                stderr=f"Execution timed out after {self.timeout_seconds} seconds.",
                exit_code=-1,
                execution_time_seconds=round(elapsed, 3)
            )
        except Exception as e:
            elapsed = time.time() - start_time
            return SandboxExecutionResult(
                passed=False,
                total_tests=0,
                failures=1,
                errors=1,
                stdout="",
                stderr=f"Sandbox execution harness failure: {str(e)}",
                exit_code=-1,
                execution_time_seconds=round(elapsed, 3)
            )
        finally:
            # Cleanup temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _parse_pytest_output(self, stdout: str, exit_code: int) -> tuple[bool, int, int, int]:
        """
        Extracts test counts from pytest terminal output.
        Returns: (passed: bool, total: int, failures: int, errors: int)
        """
        passed = (exit_code == 0)
        
        # Regex to match summary line like: "=== 1 failed, 2 passed in 0.12s ==="
        passed_match = re.search(r"(\d+)\s+passed", stdout)
        failed_match = re.search(r"(\d+)\s+failed", stdout)
        error_match = re.search(r"(\d+)\s+error", stdout)

        passed_count = int(passed_match.group(1)) if passed_match else 0
        failed_count = int(failed_match.group(1)) if failed_match else 0
        error_count = int(error_match.group(1)) if error_match else 0

        total_count = passed_count + failed_count + error_count
        if total_count == 0 and exit_code != 0:
            failed_count = 1
            total_count = 1

        return (passed, total_count, failed_count, error_count)
