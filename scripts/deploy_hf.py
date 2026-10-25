"""Deploy (or update) the app as a Hugging Face Docker Space.

Why not `git push`? Hugging Face rejects pushes that contain binary files
(the sample policy PDF is in this repo's history). The Hub's upload API
stores binaries correctly and uploads only the current files, no history.

What it does:
  1. checks you're logged in (`hf auth login`, or HF_TOKEN in the environment)
  2. creates the Space <your-username>/<name> with the Docker SDK (if missing)
  3. stores GEMINI_API_KEY from backend/.env as a Space *secret*
     (never printed, never uploaded as a file)
  4. sets demo limits as Space variables
  5. uploads the source (without .env, venvs, node_modules, runtime state)
  6. uploads a Space README with the YAML header Spaces needs (port 7860)

The Space then builds the Dockerfile itself (5-10 minutes the first time).

Usage (from the repo root, with the backend venv):
  backend\\.venv\\Scripts\\pip install huggingface_hub
  backend\\.venv\\Scripts\\hf auth login        # paste a token with WRITE access
  backend\\.venv\\Scripts\\python scripts\\deploy_hf.py --dry-run
  backend\\.venv\\Scripts\\python scripts\\deploy_hf.py

Re-run the same command to deploy updates.
"""

import argparse
import fnmatch
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

IGNORE = [
    ".git/*", "**/.git/*",
    "**/.env", ".env",
    "**/.venv/*", "**/node_modules/*", "**/__pycache__/*", "**/.pytest_cache/*",
    "backend/storage/*", "backend/.cache/*", "frontend/dist/*",
    "backend/eval/results/*", "backend/redteam/results/*",
    "docs/architecture-atlas/*",  # documentation, not needed to run the app
    "SECURITY.md",  # unfinished draft
    "README.md",  # replaced by the Space README below
]

# Public demo defaults: tighter than the code defaults so a shared link
# can't exhaust the free Gemini quota. Change them later in the Space settings.
VARIABLES = {
    "QUESTIONS_PER_IP_PER_HOUR": "20",
    "UPLOADS_PER_IP_PER_HOUR": "5",
    "QUESTIONS_PER_DAY_GLOBAL": "300",
}


def space_readme(github_url: str | None) -> str:
    link = f"\nSource code: {github_url}\n" if github_url else ""
    return f"""---
title: Am I Covered
emoji: 🩺
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
short_description: Ask your US health insurance policy; cited, verified answers
---

# Am I Covered?

Ask a question about a US health insurance policy in plain English and get a verdict,
the exact clause and page it comes from, the federal rules that protect you, and what
to ask your insurer. Use the built-in sample policy (fictional) or upload your own PDF.
Uploads are deleted after 24 hours. Not legal or medical advice.
{link}"""


def read_env_value(key: str) -> str | None:
    env = ROOT / "backend" / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"').strip("'") or None
    return None


def files_to_upload() -> list[str]:
    out = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if any(fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.removeprefix("**/")) for pat in IGNORE):
            continue
        if any(part in (".git", ".venv", "node_modules", "__pycache__", ".pytest_cache") for part in p.parts):
            continue
        out.append(rel)
    return sorted(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="am-i-covered", help="Space name (default: am-i-covered)")
    parser.add_argument("--private", action="store_true", help="make the Space private")
    parser.add_argument("--github-url", default="https://github.com/AbdullahHAK/DocuMind-AI")
    parser.add_argument("--dry-run", action="store_true", help="list what would be uploaded and stop")
    args = parser.parse_args()

    files = files_to_upload()
    total = sum((ROOT / f).stat().st_size for f in files)
    print(f"{len(files)} files, {total / 1024:.0f} KB would be uploaded")
    leaked = [f for f in files if f.endswith(".env") or "/.venv/" in f or f.startswith("backend/storage/")]
    if leaked:
        print("refusing to deploy, these must never be uploaded:", leaked)
        return 1
    if args.dry_run:
        for f in files:
            print("  ", f)
        print("\ndry run: nothing uploaded")
        return 0

    key = read_env_value("GEMINI_API_KEY")
    if not key:
        print("GEMINI_API_KEY not found in backend/.env - add it first (free key: https://aistudio.google.com/apikey)")
        return 1

    from huggingface_hub import HfApi
    from huggingface_hub.errors import HfHubHTTPError

    api = HfApi()
    try:
        user = api.whoami()["name"]
    except Exception:
        print("Not logged in to Hugging Face. Run:  backend\\.venv\\Scripts\\hf auth login  (token with WRITE access)")
        return 1
    repo_id = f"{user}/{args.name}"
    print(f"deploying to https://huggingface.co/spaces/{repo_id}")

    try:
        api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
        api.add_space_secret(repo_id, "GEMINI_API_KEY", key, description="Google Gemini API key")
        for name, value in VARIABLES.items():
            api.add_space_variable(repo_id, name, value)
        api.upload_folder(
            repo_id=repo_id, repo_type="space", folder_path=str(ROOT),
            ignore_patterns=IGNORE, commit_message="Deploy from local checkout",
        )
        api.upload_file(
            path_or_fileobj=space_readme(args.github_url).encode("utf-8"), path_in_repo="README.md",
            repo_id=repo_id, repo_type="space", commit_message="Space README",
        )
    except HfHubHTTPError as exc:
        print(f"Hugging Face rejected the request: {exc}")
        return 1

    print("\nuploaded. The Space is now building (5-10 min the first time). Watch the Logs tab:")
    print(f"  https://huggingface.co/spaces/{repo_id}?logs=container")
    print("when it says 'Application startup complete', your app is live at:")
    print(f"  https://{user.lower()}-{args.name}.hf.space")
    return 0


if __name__ == "__main__":
    sys.exit(main())
