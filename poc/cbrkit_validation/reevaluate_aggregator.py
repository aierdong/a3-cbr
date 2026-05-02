"""
重新评估 CBRKit aggregator 模块

根据用户反馈，需要重新评估 cbrkit.sim.aggregator 是否能满足需求。
"""

import sys


def deep_dive_aggregator():
    """深入探索 cbrkit.sim.aggregator 的实际能力"""
    try:
        from cbrkit.sim import aggregator
        import inspect

        print("=" * 80)
        print("CBRKit Aggregator 模块深度分析")
        print("=" * 80)
        print()

        # 1. 列出所有可用函数
        print("1. 可用的聚合函数:")
        funcs = [name for name in dir(aggregator) if not name.startswith('_') and callable(getattr(aggregator, name))]
        for func_name in funcs:
            func = getattr(aggregator, func_name)
            print(f"\n   {func_name}:")

            # 获取函数签名
            try:
                sig = inspect.signature(func)
                print(f"   签名: {func_name}{sig}")
            except:
                print(f"   签名: 无法获取")

            # 获取文档字符串
            if func.__doc__:
                doc_lines = func.__doc__.strip().split('\n')
                print(f"   文档: {doc_lines[0][:100]}")

        print("\n" + "=" * 80)
        print("2. 测试加权聚合场景")
        print("=" * 80)
        print()

        # 测试场景：多个候选，每个候选有多个维度的分值
        # 需求：对每个维度应用不同的权重，然后聚合

        # 模拟数据结构
        candidates = {
            'case_1': {
                'vector_sim': 0.95,
                'semantic_sim': 0.88,
                'structured_sim': 0.75,
                'business_score': 0.82
            },
            'case_2': {
                'vector_sim': 0.87,
                'semantic_sim': 0.92,
                'structured_sim': 0.68,
                'business_score': 0.79
            },
            'case_3': {
                'vector_sim': 0.82,
                'semantic_sim': 0.85,
                'structured_sim': 0.80,
                'business_score': 0.88
            }
        }

        weights = {
            'vector_sim': 0.3,
            'semantic_sim': 0.4,
            'structured_sim': 0.1,
            'business_score': 0.2
        }

        print("测试数据:")
        print(f"  候选数: {len(candidates)}")
        print(f"  维度数: {len(weights)}")
        print(f"  权重: {weights}")
        print()

        # 尝试使用 aggregator 的函数
        print("3. 尝试使用 aggregator 函数:")
        print()

        # 测试 pooling 函数（如果存在）
        if hasattr(aggregator, 'pooling'):
            print("   测试 aggregator.pooling:")
            try:
                # 尝试不同的调用方式
                print("   尝试调用...")

                # 方式1：传递分值字典
                test_scores = list(candidates['case_1'].values())
                test_weights = list(weights.values())

                # 查看 pooling 函数的参数
                sig = inspect.signature(aggregator.pooling)
                print(f"   pooling 签名: {sig}")

                # 尝试调用
                # result = aggregator.pooling(test_scores, test_weights)
                # print(f"   结果: {result}")

            except Exception as e:
                print(f"   错误: {e}")

        # 测试 pooling_weights 函数（如果存在）
        if hasattr(aggregator, 'pooling_weights'):
            print("\n   测试 aggregator.pooling_weights:")
            try:
                sig = inspect.signature(aggregator.pooling_weights)
                print(f"   pooling_weights 签名: {sig}")

                # 查看文档
                if aggregator.pooling_weights.__doc__:
                    print(f"   文档: {aggregator.pooling_weights.__doc__[:200]}")

            except Exception as e:
                print(f"   错误: {e}")

        print("\n" + "=" * 80)
        print("4. 分析结论")
        print("=" * 80)
        print()

        print("需要回答的关键问题:")
        print("1. aggregator 是否支持加权聚合？")
        print("2. 输入格式是什么？（字典、列表、矩阵？）")
        print("3. 是否需要完整的 casebase，还是可以只处理候选集？")
        print("4. 是否支持缺失分项的处理？")
        print()

        return True

    except ImportError as e:
        print(f"CBRKit 导入失败: {e}")
        return False
    except Exception as e:
        print(f"分析过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_actual_usage():
    """尝试实际使用 aggregator"""
    try:
        from cbrkit.sim import aggregator
        import numpy as np

        print("\n" + "=" * 80)
        print("5. 实际使用测试")
        print("=" * 80)
        print()

        # 尝试构建符合 CBRKit 预期的数据结构
        print("尝试不同的数据结构:")
        print()

        # 测试1: 简单列表
        print("测试1: 简单分值列表")
        scores = [0.95, 0.88, 0.75, 0.82]
        weights = [0.3, 0.4, 0.1, 0.2]
        print(f"  分值: {scores}")
        print(f"  权重: {weights}")

        # 手动计算期望结果
        expected = sum(s * w for s, w in zip(scores, weights))
        print(f"  期望结果: {expected:.4f}")

        # 尝试使用 aggregator
        if hasattr(aggregator, 'pooling'):
            try:
                # 需要查看实际的函数签名来正确调用
                import inspect
                sig = inspect.signature(aggregator.pooling)
                params = sig.parameters
                print(f"\n  pooling 参数: {list(params.keys())}")

                # 根据参数尝试调用
                # 这里需要根据实际签名调整

            except Exception as e:
                print(f"  调用失败: {e}")

        print()

        # 测试2: 矩阵形式（多个候选）
        print("测试2: 矩阵形式（多个候选）")
        score_matrix = np.array([
            [0.95, 0.88, 0.75, 0.82],  # case_1
            [0.87, 0.92, 0.68, 0.79],  # case_2
            [0.82, 0.85, 0.80, 0.88],  # case_3
        ])
        print(f"  分值矩阵形状: {score_matrix.shape}")
        print(f"  权重: {weights}")

        # 手动计算期望结果
        expected_results = score_matrix @ np.array(weights)
        print(f"  期望结果: {expected_results}")

        print()

    except Exception as e:
        print(f"使用测试异常: {e}")
        import traceback
        traceback.print_exc()


def provide_recommendation():
    """基于分析提供建议"""
    print("\n" + "=" * 80)
    print("6. 建议")
    print("=" * 80)
    print()

    print("基于当前分析，需要确认以下几点:")
    print()
    print("A. 如果 aggregator.pooling 支持加权聚合:")
    print("   ✓ 可以使用 CBRKit 的 aggregator")
    print("   ✓ 需要适配输入输出格式")
    print("   ✓ 设计文档应更新为「使用 CBRKit aggregator」")
    print()
    print("B. 如果 aggregator 不支持或格式不匹配:")
    print("   ✓ 保持当前的自实现 ScoreAggregator")
    print("   ✓ 逻辑简单，完全可控")
    print()
    print("C. 混合方案:")
    print("   ✓ 使用 CBRKit 的相似度计算功能")
    print("   ✓ 自实现加权聚合逻辑")
    print("   ✓ 保持适配层清晰")
    print()

    print("关键决策因素:")
    print("1. aggregator 的输入格式是否与本规格的数据结构匹配？")
    print("2. aggregator 是否支持缺失分项的处理？")
    print("3. aggregator 是否需要完整的 casebase？")
    print("4. 使用 aggregator 的学习成本 vs 自实现的维护成本？")
    print()


if __name__ == "__main__":
    success = deep_dive_aggregator()
    if success:
        test_actual_usage()
    provide_recommendation()
