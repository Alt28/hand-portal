import os
import subprocess
import sys


def prepare_vercel_opencv():
    if os.environ.get("VERCEL") != "1":
        return
    subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", "opencv-contrib-python"], check=True)
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--force-reinstall",
                    "opencv-contrib-python-headless>=4.11,<5"], check=True)


if __name__ == "__main__":
    prepare_vercel_opencv()
    from hand_tracker import download_model

    print(download_model())
