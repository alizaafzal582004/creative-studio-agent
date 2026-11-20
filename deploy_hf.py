"""Deploy (or update) on Hugging Face Spaces: python deploy_hf.py

Needs HF_TOKEN in .env (huggingface.co → Settings → Access Tokens → a 'Write' token).
This script:
  1) creates the Space on your account (Docker, public) if it doesn't exist
  2) uploads the code (.env, venv, input/output/models and videos are NOT uploaded)
  3) stores the API keys from .env as Space 'Secrets' (never in the code)
Tokens and keys are never printed."""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from huggingface_hub import HfApi

SPACE_NAME = "ai-creative-studio"
SECRET_KEYS = ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GEMINI_API_KEY", "GEMINI_MODEL",
               "PIXABAY_API_KEY", "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "APP_PASSWORD"]
IGNORE = [".env", ".git/*", "venv/*", "**/__pycache__/*", "__pycache__/*", "input/*", "output/*", "models/*",
          "*.mp4", "*.mp3", ".streamlit/secrets.toml", "deploy_hf.py", "README.md"]
# Hugging Face needs this YAML header at the top of the Space's README (GitHub's README stays clean)
HF_HEADER = """---
title: AI Creative Studio
emoji: 🎬
colorFrom: gray
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Turn long videos into viral Shorts with AI
---

"""


def main():
    env = dotenv_values(".env")
    token = env.get("HF_TOKEN") or os.getenv("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not found in .env. Go to huggingface.co → Settings → Access Tokens, "
                         "create a 'Write' token and add  HF_TOKEN=...  to .env.")
    api = HfApi(token=token)
    user = api.whoami()["name"]
    repo_id = f"{user}/{SPACE_NAME}"
    print(f"1/3  Space: {repo_id} (public, Docker)...")
    api.create_repo(repo_id=repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)

    print("2/3  Uploading code...")
    api.upload_folder(folder_path=".", repo_id=repo_id, repo_type="space", ignore_patterns=IGNORE,
                      commit_message="Deploy: AI Creative Studio")
    readme = HF_HEADER + Path("README.md").read_text(encoding="utf-8")
    api.upload_file(path_or_fileobj=readme.encode("utf-8"), path_in_repo="README.md", repo_id=repo_id,
                    repo_type="space", commit_message="Deploy: README")

    print("3/3  Storing API keys as Space secrets (not in the code)...")
    added = []
    for key in SECRET_KEYS:
        value = env.get(key)
        if value:
            api.add_space_secret(repo_id=repo_id, key=key, value=value)
            added.append(key)
    print(f"     Secrets: {', '.join(added)}")
    print(f"\n✅ Deployed. The build takes 5-10 minutes, then the website is live at:\n"
          f"   https://huggingface.co/spaces/{repo_id}")


if __name__ == "__main__":
    sys.exit(main())
