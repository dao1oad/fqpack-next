from typing import Callable, Dict, List, Optional, Type

from freshquant.workflow.base.node_type import BaseNode


class NodeRegistry:
    """节点注册表"""

    def __init__(self):
        self._registry: Dict[str, Type[BaseNode]] = {}
        self._categories: Dict[str, List[str]] = {}

    def register(
        self,
        node_id: Optional[str] = None,
        category: str = "custom",
        version: str = "1.0.0",
        author: str = "",
        tags: Optional[List[str]] = None,
    ) -> Callable:
        """装饰器：注册节点"""

        def decorator(node_class: Type[BaseNode]) -> Type[BaseNode]:
            actual_id = node_id or node_class.__name__

            # 设置元数据
            node_class.NODE_ID = actual_id
            node_class.CATEGORY = category
            node_class.VERSION = version
            node_class.AUTHOR = author
            node_class.TAGS = tags or []

            # 验证方法
            required = [
                'input_schema',
                'output_schema',
                'execute',
            ]
            for method in required:
                if not hasattr(node_class, method):
                    raise ValueError(f"Node {actual_id} must implement {method}()")

            # 注册
            self._registry[actual_id] = node_class
            if category not in self._categories:
                self._categories[category] = []
            self._categories[category].append(actual_id)

            print(f"✓ Registered node: {actual_id} ({category})")
            return node_class

        return decorator

    def get_node(self, node_id: str) -> Type[BaseNode]:
        """获取节点类"""
        if node_id not in self._registry:
            raise ValueError(f"Node '{node_id}' not found")
        return self._registry[node_id]

    def create_node(self, node_id: str) -> BaseNode:
        """创建节点实例"""
        return self.get_node(node_id)()

    def list_nodes(self, category: Optional[str] = None) -> Dict[str, dict]:
        """列出所有节点"""
        result = {}
        for node_id, node_class in self._registry.items():
            if category and node_class.CATEGORY != category:
                continue
            result[node_id] = {
                "name": node_class.NODE_NAME or node_id,
                "description": node_class.NODE_DESCRIPTION,
                "category": node_class.CATEGORY,
                "version": node_class.VERSION,
            }
        return result


# 创建全局实例
node_registry = NodeRegistry()
