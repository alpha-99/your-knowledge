"""
LangGraph 工作流编排 — 知识库采集→分析→整理→审核→保存 流水线

核心设计：
  collect → analyze → organize → review ─(通过)→ save → END
                        ↑                │
                        └── (未通过, 最多3次) ─┘

审核循环 (Review Loop) 是本项目的核心教学点:
  - review 节点按 4 个维度评分 (1-5)
  - overall_score >= 3.5 → 通过，进入 save
  - overall_score < 3.5  → 未通过，回到 organize 修正后重新审核
  - 第 3 次迭代强制通过，防止无限循环
"""

from langgraph.graph import END, StateGraph

from workflows.nodes import (
    analyze_node,
    collect_node,
    organize_node,
    review_node,
    save_node,
)
from workflows.state import KBState


def _review_router(state: KBState) -> str:
    """审核节点后的条件路由

    根据 review_passed 决定下一步:
      - True  → save (保存)
      - False → organize (回到整理节点修正)
    """
    return "save" if state["review_passed"] else "organize"


def build_graph() -> StateGraph:
    """构建并返回编译后的 LangGraph 工作流

    Returns:
        编译后的 StateGraph 实例 (CompiledGraph)
    """
    graph = StateGraph(KBState)

    graph.add_node("collect", collect_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("organize", organize_node)
    graph.add_node("review", review_node)
    graph.add_node("save", save_node)

    graph.add_edge("collect", "analyze")
    graph.add_edge("analyze", "organize")
    graph.add_edge("organize", "review")

    graph.add_conditional_edges(
        "review",
        _review_router,
        {
            "save": "save",
            "organize": "organize",
        },
    )

    graph.add_edge("save", END)

    graph.set_entry_point("collect")

    return graph.compile()


if __name__ == "__main__":
    app = build_graph()

    initial_state: KBState = {
        "sources": [],
        "analyses": [],
        "articles": [],
        "review_feedback": "",
        "review_passed": False,
        "iteration": 0,
        "cost_tracker": {},
    }

    print("=" * 60)
    print("LangGraph 知识库工作流 启动")
    print("=" * 60)

    for step in app.stream(initial_state):
        node_name = list(step.keys())[0]
        node_output = step[node_name]

        print(f"\n--- [{node_name}] 节点输出 ---")

        if node_name == "collect":
            count = len(node_output.get("sources", []))
            print(f"  采集数据: {count} 条")

        elif node_name == "analyze":
            count = len(node_output.get("analyses", []))
            print(f"  分析条目: {count} 条")

        elif node_name == "organize":
            articles = node_output.get("articles", [])
            print(f"  整理条目: {len(articles)} 条")
            for art in articles[:3]:
                print(f"    - {art['id']}: {art['title'][:50]}")

        elif node_name == "review":
            passed = node_output.get("review_passed", False)
            iteration = node_output.get("iteration", 0)
            feedback = node_output.get("review_feedback", "")
            print(f"  审核通过: {passed}")
            print(f"  当前迭代: {iteration}/3")
            if feedback:
                print(f"  反馈: {feedback[:100]}")

        elif node_name == "save":
            print(f"  已保存到 knowledge/articles/")

    print("\n" + "=" * 60)
    print("工作流执行完成")
    print("=" * 60)
