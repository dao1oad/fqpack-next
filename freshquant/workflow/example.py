from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, Field

from freshquant.workflow.base.node_config import EdgeConfig, NodeConfig, WorkflowConfig
from freshquant.workflow.base.node_registry import node_registry
from freshquant.workflow.base.node_type import BaseNode, DataType
from freshquant.workflow.base.workflow_executor import WorkflowExecutor


class DummyInputModel(BaseModel):
    """空输入"""

    model_config = ConfigDict(extra='allow')


class SimpleOutputModel(BaseModel):
    """简单输出"""

    result: Any = Field(default=None)
    model_config = ConfigDict(extra='allow')


class LoaderOutputModel(BaseModel):
    """加载器输出"""

    stocks: list = Field(default_factory=list, description="股票列表")
    model_config = ConfigDict(extra='allow')


class FilterInputModel(BaseModel):
    """筛选器输入"""

    stocks: list = Field(default_factory=list, description="股票列表")
    model_config = ConfigDict(extra='allow')


class FilterOutputModel(BaseModel):
    """筛选器输出"""

    selected: list = Field(default_factory=list, description="筛选后的股票列表")
    model_config = ConfigDict(extra='allow')


class ExportInputModel(BaseModel):
    """导出器输入"""

    selected: list = Field(default_factory=list, description="筛选后的股票列表")
    model_config = ConfigDict(extra='allow')


class ExportOutputModel(BaseModel):
    """导出器输出"""

    status: str = Field(default="success", description="导出状态")
    model_config = ConfigDict(extra='allow')


@node_registry.register(
    node_id="simple_loader", category="data", version="1.0.0", author="framework"
)
class SimpleLoaderNode(BaseNode):
    """简单数据加载器"""

    NODE_NAME = "简单数据加载器"
    NODE_DESCRIPTION = "加载示例数据"

    @classmethod
    def input_schema(cls):
        return DummyInputModel

    @classmethod
    def output_schema(cls):
        return LoaderOutputModel

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        stocks = ["600000", "600001", "600002", "600003", "600004"]
        return {"stocks": stocks}


@node_registry.register(
    node_id="simple_filter", category="filter", version="1.0.0", author="framework"
)
class SimpleFilterNode(BaseNode):
    """简单筛选节点"""

    NODE_NAME = "简单筛选"
    NODE_DESCRIPTION = "筛选股票"

    @classmethod
    def input_schema(cls):
        return FilterInputModel

    @classmethod
    def output_schema(cls):
        return FilterOutputModel

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        stocks = inputs.get("stocks", [])
        # 简单筛选：选择前3个
        selected = stocks[:3]
        return {"selected": selected}


@node_registry.register(
    node_id="simple_export", category="output", version="1.0.0", author="framework"
)
class SimpleExportNode(BaseNode):
    """简单导出节点"""

    NODE_NAME = "简单导出"
    NODE_DESCRIPTION = "导出结果"

    @classmethod
    def input_schema(cls):
        return ExportInputModel

    @classmethod
    def output_schema(cls):
        return ExportOutputModel

    def execute(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        selected = inputs.get("selected", [])
        print(
            f"\
📊 Final result: {selected}"
        )
        return {"status": "success"}


# ============================================================================
# 使用示例
# ============================================================================


def main():
    print(
        "\
"
        + "=" * 70
    )
    print("量化选股工作流框架 - 使用示例")
    print(
        "=" * 70
        + "\
"
    )

    # 列出所有节点
    print("📦 Available nodes:")
    for node_id, info in node_registry.list_nodes().items():
        print(f"  • {node_id}: {info['name']} ({info['category']})")
    print()

    # 创建工作流
    workflow_config = WorkflowConfig(
        workflow_id="simple_workflow_001",
        name="简单选股工作流",
        description="演示工作流",
        version="1.0.0",
    )

    # 添加节点
    workflow_config.nodes.extend(
        [
            NodeConfig(
                node_id="simple_loader",
                instance_id="node_1_load",
                name="数据加载",
                inputs={},
            ),
            NodeConfig(
                node_id="simple_filter",
                instance_id="node_2_filter",
                name="股票筛选",
                inputs={},
            ),
            NodeConfig(
                node_id="simple_export",
                instance_id="node_3_export",
                name="结果导出",
                inputs={},
            ),
        ]
    )

    # 连接节点
    workflow_config.edges.extend(
        [
            EdgeConfig(
                source="node_1_load",
                source_port="stocks",
                target="node_2_filter",
                target_port="stocks",
            ),
            EdgeConfig(
                source="node_2_filter",
                source_port="selected",
                target="node_3_export",
                target_port="selected",
            ),
        ]
    )

    # 保存工作流
    workflow_json = workflow_config.to_json()
    print("💾 Workflow JSON:")
    print(workflow_json)
    print()

    # 执行工作流
    executor = WorkflowExecutor()
    results = executor.execute(workflow_config)

    # 查看结果
    print("📈 Results:")
    for node_id, result in results.items():
        print(f"  {node_id}: {result}")
    print()


if __name__ == "__main__":
    main()
