import os
import shutil
import subprocess
from getpass import getpass

# ========== 配置部分 ==========
GIT_USERNAME = "cnlyj6"
GIT_EMAIL = "g1910198192@gmail.com"
REPO_NAME = "code"
SOURCE_DIR = "/content/drive/MyDrive"
CLONE_DIR = f"/content/{REPO_NAME}"

# ========== 初始化 ==========
# 删除旧 clone 目录
shutil.rmtree(CLONE_DIR, ignore_errors=True)

# 设置 Git 信息
subprocess.run(["git", "config", "--global", "user.name", GIT_USERNAME])
subprocess.run(["git", "config", "--global", "user.email", GIT_EMAIL])

# 输入 GitHub Token
token = getpass("GitHub Token: ")

# 克隆仓库
repo_url = f"https://{GIT_USERNAME}:{token}@github.com/{GIT_USERNAME}/{REPO_NAME}.git"
clone_result = subprocess.run(["git", "clone", repo_url], cwd="/content")

if clone_result.returncode != 0:
    raise RuntimeError("❌ 仓库克隆失败，请检查 Token 或权限")

# ========== 复制内容 ==========
# 检查源目录
if not os.path.exists(SOURCE_DIR):
    raise FileNotFoundError(f"❌ 找不到要上传的目录: {SOURCE_DIR}")

# 删除 clone 的仓库中的所有文件
print("🧹 清空旧仓库内容...")
for filename in os.listdir(CLONE_DIR):
    file_path = os.path.join(CLONE_DIR, filename)
    if filename == ".git":
        continue  # 不删除 .git 目录
    if os.path.isfile(file_path) or os.path.islink(file_path):
        os.unlink(file_path)
    elif os.path.isdir(file_path):
        shutil.rmtree(file_path)

# 拷贝内容
print("📂 正在复制目录...")
for item in os.listdir(SOURCE_DIR):
    s = os.path.join(SOURCE_DIR, item)
    d = os.path.join(CLONE_DIR, item)
    if os.path.isdir(s):
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)

# ========== Git 操作 ==========
os.chdir(CLONE_DIR)

# 确保当前是 git 仓库
if not os.path.exists(os.path.join(CLONE_DIR, ".git")):
    raise RuntimeError("❌ 当前目录不是 Git 仓库，请检查 .git 是否存在")

# 添加改动
subprocess.run(["git", "add", "."], check=True)

# 检查是否有改动
status = subprocess.run(["git", "status", "--porcelain"], stdout=subprocess.PIPE)
if not status.stdout.strip():
    print("⚠️ 没有文件改动，跳过提交和推送")
else:
    # 提交更改
    subprocess.run(["git", "commit", "-m", "📤 Upload directory from Colab"], check=True)

    # 推送
    push_result = subprocess.run(["git", "push", "origin", "main"])

    if push_result.returncode != 0:
        raise RuntimeError("❌ 推送失败，请检查 Token 或网络")
    else:
        print("✅ 推送成功！请在 GitHub 查看")

# 显示当前路径确认
print("✅ 当前仓库路径:", os.getcwd())
