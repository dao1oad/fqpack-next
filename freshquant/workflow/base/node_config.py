import json
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class NodeConfig:
    """节点配置"""

    node_id: str
    instance_id: str
    name: str = ""
    inputs: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class EdgeConfig:
    """节点连接配置"""

    source: str
    source_port: str
    target: str
    target_port: str


@dataclass
class WorkflowConfig:
    """工作流配置"""

    workflow_id: str
    name: str
    description: str = ""
    version: str = "1.0.0"
    nodes: List[NodeConfig] = field(default_factory=list)
    edges: List[EdgeConfig] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "instance_id": n.instance_id,
                    "name": n.name,
                    "inputs": n.inputs,
                    "description": n.description,
                }
                for n in self.nodes
            ],
            "edges": [
                {
                    "source": e.source,
                    "source_port": e.source_port,
                    "target": e.target,
                    "target_port": e.target_port,
                }
                for e in self.edges
            ],
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict) -> "WorkflowConfig":
        nodes = [NodeConfig(**n) for n in data["nodes"]]
        edges = [EdgeConfig(**e) for e in data["edges"]]
        return cls(
            workflow_id=data["workflow_id"],
            name=data["name"],
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            nodes=nodes,
            edges=edges,
            metadata=data.get("metadata", {}),
        )
