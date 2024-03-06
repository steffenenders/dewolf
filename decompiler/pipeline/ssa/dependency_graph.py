from functools import reduce
from typing import Iterable, Iterator, List, Optional, Set

from decompiler.structures.graphs.cfg import ControlFlowGraph
from decompiler.structures.interferencegraph import InterferenceGraph
from decompiler.structures.pseudo import Expression, Operation, OperationType, instructions
from decompiler.structures.pseudo.expressions import Variable
from decompiler.structures.pseudo.instructions import Assignment
from decompiler.structures.pseudo.operations import Call
from networkx import DiGraph, weakly_connected_components


def _assignments_in_cfg(cfg: ControlFlowGraph) -> Iterator[Assignment]:
    """Yield all interesting assignments for the dependency graph."""
    for instr in cfg.instructions:
        # ignores assignments with multiple values... These are currently poorly defined, so idk how they need to be handled
        if isinstance(instr, Assignment) and isinstance(instr.destination, Variable):
            yield instr


class DependencyGraph(DiGraph):
    def __init__(self, interference_graph: InterferenceGraph):
        super().__init__()
        self.interference_graph = interference_graph

    @classmethod
    def from_cfg(cls, cfg: ControlFlowGraph, interference_graph: InterferenceGraph):
        """
        Construct the dependency graph of the given CFG, i.e. adds an edge between two variables if they depend on each other.
            - Add an edge the definition to at most one requirement for each instruction.
            - All variables that where not defined via Phi-functions before have out-degree of at most 1, because they are defined at most once.
            - Variables that are defined via Phi-functions can have one successor for each required variable of the Phi-function.
        """
        dependency_graph = cls(interference_graph)
        dependency_graph.add_nodes_from(interference_graph.nodes)

        for instruction in _assignments_in_cfg(cfg):
            defined_variable = instruction.destination

            for used_variable, score in _expression_dependencies(instruction.value).items():
                dependency_graph.add_edge(defined_variable, used_variable, score=score)

        return dependency_graph

    def _non_interfering_requirements(self, requirements: List[Variable], defined_variable: Variable) -> Optional[Variable]:
        """Get the unique non-interfering requirement if it exists, otherwise we return None."""
        non_interfering_requirement = None
        for required_variable in requirements:
            if self._variables_can_have_same_name(defined_variable, required_variable):
                if non_interfering_requirement:
                    return None
                non_interfering_requirement = required_variable
        return non_interfering_requirement

    def _variables_can_have_same_name(self, source: Variable, sink: Variable) -> bool:
        """
        Two variable can have the same name, if they have the same type, are both aliased or both non-aliased variables, and if they
        do not interfere.

        :param source: The potential source vertex.
        :param sink: The potential sink vertex
        :return: True, if the given variables can have the same name, and false otherwise.
        """
        if self.interference_graph.are_interfering(source, sink) or source.type != sink.type or source.is_aliased != sink.is_aliased:
            return False
        if source.is_aliased and sink.is_aliased and source.name != sink.name:
            return False
        return True

    def get_components(self) -> Iterable[Set[Variable]]:
        """Returns the weakly connected components of the dependency graph."""
        for component in weakly_connected_components(self):
            yield set(component)


def _expression_dependencies(expression: Expression) -> dict[Variable, float]:
    match expression:
        case Variable():
            return {expression: 1.0}
        case Operation():
            operation_type_penalty = {
                OperationType.call: 0.5,
                OperationType.address: 0,
                OperationType.dereference: 0,
                OperationType.member_access: 0,
            }.get(expression.operation, 1.0)

            dependencies: dict[Variable, float] = reduce(dict.__or__, (_expression_dependencies(operand) for operand in expression.operands))
            for var in dependencies:
                dependencies[var] /= len(dependencies)
                dependencies[var] *= operation_type_penalty
                if expression.type != var.type:
                    dependencies[var] = 0
            return dependencies
        case _:
            return {}
