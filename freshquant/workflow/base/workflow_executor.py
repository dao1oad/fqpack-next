import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

import networkx as nx

from freshquant.workflow.base.node_config import WorkflowConfig
from freshquant.workflow.base.node_registry import node_registry
from freshquant.workflow.base.node_type import BaseNode


class WorkflowExecutor:
    """工作流执行引擎"""

    def __init__(self, cache_dir: Optional[str] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.cache_dir = cache_dir
        self.node_instances: Dict[str, BaseNode] = {}
        self.node_results: Dict[str, Dict[str, Any]] = {}
        self.execution_log: List[Dict] = []

    def prepare(self, workflow_config: WorkflowConfig) -> None:
        """准备工作流"""
        self.workflow_config = workflow_config
        self.node_instances = {}

        for node_config in workflow_config.nodes:
            try:
                node = node_registry.create_node(node_config.node_id)
                self.node_instances[node_config.instance_id] = node
                self.logger.info(f"Created node instance: {node_config.instance_id}")
            except Exception as e:
                raise RuntimeError(
                    f"Failed to create node {node_config.instance_id}: {e}"
                )

    def build_dag(self):
        """构建DAG"""
        if nx is None:
            raise RuntimeError("networkx is required for DAG building")

        graph = nx.DiGraph()

        for node_config in self.workflow_config.nodes:
            graph.add_node(node_config.instance_id)

        for edge in self.workflow_config.edges:
            graph.add_edge(edge.source, edge.target)

        if not nx.is_directed_acyclic_graph(graph):
            raise ValueError("Workflow contains cycles")

        in_degree = dict(graph.in_degree())
        return graph, in_degree

    def execute(
        self,
        workflow_config: WorkflowConfig,
        use_cache: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """执行工作流"""
        print(
            f"\
{'='*70}"
        )
        print(f"Workflow: {workflow_config.name}")
        print(f"ID: {workflow_config.workflow_id}")
        print(
            f"{'='*70}\
"
        )

        start_time = time.time()

        # 准备
        self.prepare(workflow_config)

        # 构建DAG
        graph, in_degree = self.build_dag()

        # 映射
        node_configs = {n.instance_id: n for n in workflow_config.nodes}
        edges_to_node = defaultdict(list)
        for edge in workflow_config.edges:
            edges_to_node[edge.target].append(
                (edge.source, edge.source_port, edge.target_port)
            )

        # 拓扑排序
        topo_order = list(nx.topological_sort(graph))
        print(
            f"Execution order: {' → '.join(topo_order)}\
"
        )

        # 执行
        self.node_results = {}
        queue = []
        current_in_degree = in_degree.copy()

        for node_id in topo_order:
            if current_in_degree[node_id] == 0:
                queue.append(node_id)

        while queue:
            current_node_id = queue.pop(0)
            node_config = node_configs[current_node_id]
            node_instance = self.node_instances[current_node_id]

            # 收集输入
            node_inputs = dict(node_config.inputs)

            for source_node_id, source_port, target_port in edges_to_node[
                current_node_id
            ]:
                if source_node_id not in self.node_results:
                    raise RuntimeError(f"Source node {source_node_id} not executed")
                source_result = self.node_results[source_node_id]
                if source_port not in source_result:
                    raise ValueError(
                        f"Port '{source_port}' not found in {source_node_id}"
                    )
                node_inputs[target_port] = source_result[source_port]

            # 执行
            print(f"► Executing: {current_node_id} ({node_config.node_id})")
            try:
                node_start = time.time()
                result = node_instance.execute(node_inputs)
                node_time = time.time() - node_start

                self.node_results[current_node_id] = result
                print(
                    f"  ✓ Success ({node_time:.3f}s)\
"
                )

                self.execution_log.append(
                    {
                        "node_id": current_node_id,
                        "status": "success",
                        "execution_time": node_time,
                    }
                )
            except Exception as e:
                print(
                    f"  ✗ Failed: {e}\
"
                )
                self.execution_log.append(
                    {
                        "node_id": current_node_id,
                        "status": "failed",
                        "error": str(e),
                    }
                )
                raise RuntimeError(f"Node execution failed: {e}")

            # 后继
            for successor in graph.successors(current_node_id):
                current_in_degree[successor] -= 1
                if current_in_degree[successor] == 0:
                    queue.append(successor)

        total_time = time.time() - start_time
        print(f"{'='*70}")
        print(f"✓ Workflow completed in {total_time:.3f}s")
        print(
            f"{'='*70}\
"
        )

        return self.node_results
