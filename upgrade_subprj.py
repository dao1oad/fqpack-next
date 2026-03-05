"""
升级子项目同步脚本

将父目录的子项目镜像同步到 morningglory/ 目录。
功能等效于 upgrade_subprj.bat 的 Python 实现。
"""

from pathlib import Path
import shutil
import filecmp
import time


# 排除的目录
EXCLUDE_DIRS = {".git", "__pycache__", ".aider.tags.cache.v3", ".venv", "node_modules", ".pytest_cache", "dist", "build"}

# 排除的文件模式
EXCLUDE_PATTERNS = {"*.egg-info", ".aider.chat.history.md", "*.pyc", ".DS_Store"}


def should_exclude(name: str, is_dir: bool) -> bool:
    """判断是否应排除该文件/目录"""
    if is_dir:
        return name in EXCLUDE_DIRS
    # 简单模式匹配
    for pattern in EXCLUDE_PATTERNS:
        if pattern.startswith("*."):
            if name.endswith(pattern[1:]):
                return True
        elif name == pattern:
            return True
    return False


def mirror_sync(src: Path, dst: Path) -> dict:
    """
    镜像同步目录（等效于 robocopy /MIR）

    Args:
        src: 源目录
        dst: 目标目录

    Returns:
        统计信息字典
    """
    stats = {"copied": 0, "deleted": 0, "skipped": 0}

    if not src.exists():
        print(f"⚠️  源目录不存在: {src}")
        return stats

    # 确保目标目录存在
    dst.mkdir(parents=True, exist_ok=True)

    # 1. 复制/更新源文件到目标
    for item in src.rglob("*"):
        rel_path = item.relative_to(src)
        dst_item = dst / rel_path

        # 检查是否排除
        parts = rel_path.parts
        if any(should_exclude(p, True) for p in parts):
            continue

        if item.is_file():
            if any(should_exclude(item.name, False) for _ in [0]):
                stats["skipped"] += 1
                continue

            # 复制文件（如果不存在或不同）
            if not dst_item.exists() or not filecmp.cmp(item, dst_item, shallow=False):
                dst_item.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dst_item)
                stats["copied"] += 1
                print(f"  ✓ {rel_path}")
            else:
                stats["skipped"] += 1

    # 2. 删除目标中多余的文件/目录
    for item in sorted(dst.rglob("*"), key=lambda x: len(x.parts), reverse=True):
        rel_path = item.relative_to(dst)
        src_item = src / rel_path

        if not src_item.exists():
            # 检查是否排除
            parts = rel_path.parts
            if any(should_exclude(p, True) for p in parts):
                continue

            if item.is_file():
                if any(should_exclude(item.name, False) for _ in [0]):
                    continue
                try:
                    item.unlink()
                    stats["deleted"] += 1
                    print(f"  ✗ {rel_path} (删除)")
                except (PermissionError, OSError) as e:
                    print(f"  ⚠️  无法删除: {rel_path} ({e})")

            elif item.is_dir():
                # 尝试删除空目录
                try:
                    item.rmdir()
                    stats["deleted"] += 1
                    print(f"  ✗ {rel_path}/ (删除目录)")
                except OSError:
                    pass  # 非空或权限不足，忽略

    return stats


def main():
    """主函数"""
    # 获取脚本所在目录
    script_dir = Path(__file__).parent

    # 定义要同步的子项目列表
    subprojects = ["fqchan01", "fqchan04", "fqchan06", "fqcopilot", "fqxtrade"]

    # 父目录（子项目所在位置）
    parent_dir = script_dir.parent
    # 目标基础目录
    target_base = script_dir / "morningglory"

    print("=" * 60)
    print("子项目镜像同步开始")
    print("=" * 60)

    total_stats = {"copied": 0, "deleted": 0, "skipped": 0}

    for proj in subprojects:
        src = parent_dir / proj
        dst = target_base / proj

        print(f"\n📦 同步: {proj}")
        print(f"   源: {src}")
        print(f"   目标: {dst}")

        start = time.time()
        stats = mirror_sync(src, dst)
        elapsed = time.time() - start

        print(f"   完成: {stats['copied']} 复制, {stats['deleted']} 删除, "
              f"{stats['skipped']} 跳过 ({elapsed:.2f}s)")

        for k in total_stats:
            total_stats[k] += stats[k]

    print("\n" + "=" * 60)
    print(f"总计: {total_stats['copied']} 复制, {total_stats['deleted']} 删除, "
          f"{total_stats['skipped']} 跳过")
    print("=" * 60)


if __name__ == "__main__":
    main()
