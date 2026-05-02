"""
CBRKit 实际 API 探索

根据初步验证，CBRKit 不包含预期的 Case/Query/Retriever/Similarity 类。
需要探索实际可用的 API。
"""

import sys


def explore_cbrkit_structure():
    """探索 CBRKit 的实际模块结构"""
    try:
        import cbrkit

        print("=" * 80)
        print("CBRKit 模块结构探索")
        print("=" * 80)
        print()

        # 1. 顶层模块
        print("1. 顶层可用模块/类:")
        top_level = [item for item in dir(cbrkit) if not item.startswith('_')]
        for item in top_level:
            obj = getattr(cbrkit, item)
            obj_type = type(obj).__name__
            print(f"   - {item}: {obj_type}")
        print()

        # 2. 探索 sim (similarity) 模块
        if hasattr(cbrkit, 'sim'):
            print("2. cbrkit.sim 模块:")
            sim_items = [item for item in dir(cbrkit.sim) if not item.startswith('_')]
            for item in sim_items:
                print(f"   - cbrkit.sim.{item}")
            print()

        # 3. 探索 retrieval 模块
        if hasattr(cbrkit, 'retrieval'):
            print("3. cbrkit.retrieval 模块:")
            retrieval_items = [item for item in dir(cbrkit.retrieval) if not item.startswith('_')]
            for item in retrieval_items:
                print(f"   - cbrkit.retrieval.{item}")
            print()

        # 4. 探索 loaders 模块
        if hasattr(cbrkit, 'loaders'):
            print("4. cbrkit.loaders 模块:")
            loader_items = [item for item in dir(cbrkit.loaders) if not item.startswith('_')]
            for item in loader_items:
                print(f"   - cbrkit.loaders.{item}")
            print()

        # 5. 尝试查找文档或示例
        if hasattr(cbrkit, '__doc__'):
            print("5. CBRKit 文档:")
            print(f"   {cbrkit.__doc__}")
            print()

        # 6. 检查是否有 typing 相关的类型定义
        if hasattr(cbrkit, 'typing'):
            print("6. cbrkit.typing 模块:")
            typing_items = [item for item in dir(cbrkit.typing) if not item.startswith('_')]
            for item in typing_items:
                print(f"   - cbrkit.typing.{item}")
            print()

        # 7. 尝试导入常见的子模块
        submodules_to_try = [
            'cbrkit.sim',
            'cbrkit.retrieval',
            'cbrkit.loaders',
            'cbrkit.typing',
            'cbrkit.helpers',
        ]

        print("7. 子模块导入测试:")
        for module_name in submodules_to_try:
            try:
                module = __import__(module_name, fromlist=[''])
                items = [item for item in dir(module) if not item.startswith('_')]
                print(f"   ✓ {module_name}: {len(items)} 个可用项")
                if items:
                    print(f"     示例: {', '.join(items[:5])}")
            except ImportError:
                print(f"   ✗ {module_name}: 无法导入")
        print()

        # 8. 查找可能的聚合/相似度函数
        print("8. 搜索关键功能:")
        keywords = ['aggregate', 'similarity', 'weighted', 'retrieve', 'rank', 'score']
        for keyword in keywords:
            matches = [item for item in dir(cbrkit) if keyword.lower() in item.lower()]
            if matches:
                print(f"   '{keyword}' 相关: {', '.join(matches)}")
        print()

        return True

    except ImportError as e:
        print(f"错误: CBRKit 未安装 - {e}")
        return False
    except Exception as e:
        print(f"探索过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_actual_api_pattern():
    """基于探索结果测试实际可用的 API 模式"""
    try:
        import cbrkit

        print("=" * 80)
        print("实际 API 模式测试")
        print("=" * 80)
        print()

        # 尝试不同的 API 模式

        # 模式 1: 函数式 API
        print("测试模式 1: 函数式 API")
        try:
            # 检查是否有 retrieve 函数
            if hasattr(cbrkit, 'retrieve'):
                print("   ✓ 找到 cbrkit.retrieve 函数")
                print(f"   签名: {cbrkit.retrieve.__doc__}")
            else:
                print("   ✗ 未找到 cbrkit.retrieve 函数")
        except Exception as e:
            print(f"   ✗ 测试失败: {e}")
        print()

        # 模式 2: 基于配置的 API
        print("测试模式 2: 基于配置的 API")
        try:
            if hasattr(cbrkit, 'loaders'):
                print("   ✓ 找到 cbrkit.loaders 模块")
                print("   可能支持从配置加载 casebase")
            else:
                print("   ✗ 未找到 loaders 模块")
        except Exception as e:
            print(f"   ✗ 测试失败: {e}")
        print()

        # 模式 3: 相似度计算
        print("测试模式 3: 相似度计算")
        try:
            if hasattr(cbrkit, 'sim'):
                print("   ✓ 找到 cbrkit.sim 模块")
                sim_funcs = [item for item in dir(cbrkit.sim) if not item.startswith('_')]
                print(f"   可用函数: {', '.join(sim_funcs[:10])}")
            else:
                print("   ✗ 未找到 sim 模块")
        except Exception as e:
            print(f"   ✗ 测试失败: {e}")
        print()

    except Exception as e:
        print(f"API 测试异常: {e}")
        import traceback
        traceback.print_exc()


def provide_recommendations():
    """基于探索结果提供建议"""
    print("=" * 80)
    print("结论与建议")
    print("=" * 80)
    print()

    print("关键发现:")
    print("1. CBRKit 的实际 API 与设计文档中的假设（Case/Query/Retriever/Similarity 类）不符")
    print("2. CBRKit 可能采用不同的架构模式（函数式、配置驱动等）")
    print("3. 需要查阅 CBRKit 官方文档以了解正确的使用方式")
    print()

    print("建议的行动方案:")
    print()
    print("方案 A: 深入研究 CBRKit 实际 API（推荐）")
    print("  1. 查阅 CBRKit GitHub 仓库: https://github.com/wi2trier/cbrkit")
    print("  2. 阅读官方文档和示例代码")
    print("  3. 根据实际 API 重新设计 CBROrchestrator 适配层")
    print("  4. 更新 design.md 中的集成代码")
    print()

    print("方案 B: 自行实现加权聚合（备选）")
    print("  优点:")
    print("    - 完全控制聚合逻辑")
    print("    - 无需依赖外部框架的不确定性")
    print("    - 实现简单直接")
    print("  缺点:")
    print("    - 失去 CBRKit 可能提供的高级特性")
    print("    - 需要自行维护聚合算法")
    print()

    print("方案 C: 混合方案（平衡）")
    print("  1. 使用 CBRKit 的相似度计算功能（如果可用）")
    print("  2. 自行实现加权聚合和排序逻辑")
    print("  3. 保持适配层清晰，便于后续替换")
    print()

    print("立即行动:")
    print("1. 访问 CBRKit GitHub 仓库查看最新文档")
    print("2. 运行 CBRKit 官方示例代码")
    print("3. 根据实际 API 决定采用方案 A、B 还是 C")
    print("4. 更新设计文档并重新验证")
    print()


if __name__ == "__main__":
    success = explore_cbrkit_structure()
    if success:
        test_actual_api_pattern()
    provide_recommendations()
