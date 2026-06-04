#!/usr/bin/env python3
import os
import sys

def download_model():
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("Installing huggingface_hub...")
        os.system(f"{sys.executable} -m pip install huggingface_hub")
        from huggingface_hub import hf_hub_download

    # IBM Granite 4.1 3B model
    repo_id = "lmstudio-community/granite-4.1-3b-GGUF"
    filename = "granite-4.1-3b-Q4_K_M.gguf"
    
    # Path to models directory
    models_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models"))
    os.makedirs(models_dir, exist_ok=True)
    
    dest_path = os.path.join(models_dir, filename)
    
    if os.path.exists(dest_path):
        print(f"Model already exists at {dest_path}")
        return

    print(f"Downloading {filename} from {repo_id}...")
    
    try:
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=models_dir,
            local_dir_use_symlinks=False
        )
        print(f"\nSuccess! Model downloaded to: {downloaded_path}")
    except Exception as e:
        print(f"\nFailed to download: {e}")

if __name__ == "__main__":
    download_model()
