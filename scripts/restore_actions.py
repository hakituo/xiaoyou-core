import shutil
import os
import glob

backup_dir = (
    r"d:\AI\xiaoyou-core\models\Image\ComfyUI\user\default\workflows\Actions_Backup"
)
target_dir = r"d:\AI\xiaoyou-core\models\Image\ComfyUI\user\default\workflows\Actions"


def restore_from_backup():
    print("Restoring Action workflows from backup...")

    files = glob.glob(os.path.join(backup_dir, "*.json"))
    for src in files:
        filename = os.path.basename(src)
        dst = os.path.join(target_dir, filename)

        try:
            shutil.copy2(src, dst)
            print(f"Restored {filename}")
        except Exception as e:
            print(f"Failed to restore {filename}: {e}")


if __name__ == "__main__":
    restore_from_backup()
