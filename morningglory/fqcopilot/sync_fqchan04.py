import os
import shutil
import filecmp

def sync_fqchan04_cpp_files():
    # 定义源目录和目标目录
    source_base_dir = os.path.join("..", "fqchan04", "cpp")
    target_base_dir = os.path.join("cpp")
    sub_dirs = ["chanlun", "common"]

    # 检查是否存在fqchan04目录
    if not os.path.exists(source_base_dir):
        print(f"目录 {source_base_dir} 不存在，跳过同步。")
        return

    for sub_dir in sub_dirs:
        source_dir = os.path.join(source_base_dir, sub_dir)
        target_dir = os.path.join(target_base_dir, sub_dir)

        # 如果目标目录不存在，创建它
        if not os.path.exists(target_dir):
            os.makedirs(target_dir)

        # 遍历源目录中的文件并同步到目标目录
        for filename in os.listdir(source_dir):
            source_file = os.path.join(source_dir, filename)
            target_file = os.path.join(target_dir, filename)

            # 如果文件存在且不是目录，则检查文件是否需要同步
            if os.path.isfile(source_file):
                if not os.path.exists(target_file) or not filecmp.cmp(source_file, target_file):
                    shutil.copy2(source_file, target_file)
                    print(f"同步文件: {source_file} -> {target_file}")
                else:
                    print(f"文件内容一致，跳过同步: {source_file}")

    print("同步完成。")

# 调用同步函数
sync_fqchan04_cpp_files()
