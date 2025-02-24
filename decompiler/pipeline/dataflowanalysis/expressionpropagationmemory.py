from decompiler.pipeline.commons.expressionpropagationcommons import ExpressionPropagationBase
from decompiler.structures.graphs.cfg import BasicBlock, ControlFlowGraph
from decompiler.structures.pointers import Pointers
from decompiler.structures.pseudo import Variable
from decompiler.structures.pseudo.instructions import Assignment, Instruction
from decompiler.task import DecompilerTask


class ExpressionPropagationMemory(ExpressionPropagationBase):
    name = "expression-propagation-memory"

    def __init__(self):
        ExpressionPropagationBase.__init__(self)

    def run(self, task: DecompilerTask):
        """
        Calculates pointers (and pointed by) for the cfg
        and runs EP
        :param task: decompiler task containing cfg
        """
        self._initialize_pointers(task.graph)
        super().run(task)

    def perform(self, graph, iteration) -> bool:
        """
        After performing normal propagation round, check if postponed aliased can be propagated.
        """
        is_changed = super().perform(graph, iteration)
        self._propagate_postponed_aliased_definitions()
        return is_changed

    def _definition_can_be_propagated_into_target(self, definition: Assignment, target: Instruction):
        """Tests if propagation is allowed based on set of rules, namely
        definition can be propagated into target if:
        - definition is assignment
        - it is not call assignment <--- possibly subject of change [same to EP]
        - it is not address assignment <--- possibly subject of change [same to EP]
        - definition's LHS and RHS does not define or use a GlobalVariable <--- possibly subject to change. [same to EP]
        - it is not phi function as such propagation would violate ssa [same to EP]
        - target is phi function and definition's rhs is something else than constant or variable [same to EP]
        - propagation result is longer than propagation limits in task [same to EP]
        - definition rhs in address of definition's lhs as it leads to incorrect decompilation [same to EP]
        - the variables of definition could be modified via memory access between definition and target [<---BRAND NEW :D]

        :param definition: definition to be propagated
        :param target: instruction in which definition could be propagated
        :return: true if propagation is allowed false otherwise
        """
        return isinstance(definition, Assignment) and not (
            self._is_phi(definition)
            or self._is_call_assignment(definition)
            or self._is_address_into_dereference(definition, target)
            or self._defines_unknown_expression(definition)
            or self._contains_global_variable(definition)
            or self._operation_is_propagated_in_phi(target, definition)
            or self._is_invalid_propagation_into_address_operation(target, definition)
            or self._is_aliased_postponed_for_propagation(target, definition)
            or self._definition_value_could_be_modified_via_memory_access_between_definition_and_target(definition, target)
            or self._pointer_value_used_in_definition_could_be_modified_via_memory_access_between_definition_and_target(definition, target)
        )

    def _initialize_pointers(self, cfg: ControlFlowGraph):
        """Initialize pointer information for the given cfg"""
        self._pointers_info = Pointers().from_cfg(cfg)

    def _update_block_map(self, old_instr_str: str, new_instr_str: str, basic_block: BasicBlock, index: int):
        """
        Update blocks map if instruction is changed:
        for old instruction string, remove basic block - index pair
        for new instruction string, add basic block - index pair
        """
        self._blocks_map[new_instr_str].add((basic_block, index))
        if (basic_block, index) in self._blocks_map[old_instr_str]:
            self._blocks_map[old_instr_str].remove((basic_block, index))

    def _update_use_map(self, variable: Variable, instruction: Instruction):
        """
        Update use map if instruction is changed and a variable is not being used by the instruction anymore:
        - remove the instruction from the uses-set of the variable
        - re-add the instruction to the map in order to update uses information for the instruction automatically
        """
        if variable not in instruction.requirements:
            self._use_map.remove_use(variable, instruction)
            self._use_map.add(instruction)

    def _propagate_postponed_aliased_definitions(self):
        """
        Propagate definitions of aliased variables, postponed for propagation, after everything else is propagated.
        Check before propagation, if there are no changes via aliases between definition and use.
        See _is_aliased_postponed_for_propagation method definition for an example why we do not propagate such definitions immediately.
        """
        self._initialize_maps(self._cfg)
        for var in self._postponed_aliased:
            uses = self._use_map.get(var)
            definition = self._def_map.get(var)

            if len(uses) == 1:
                instruction = uses.pop()
                if self._is_aliased_postponed_for_propagation(instruction, definition):
                    if self._definition_value_could_be_modified_via_memory_access_between_definition_and_target(
                        definition, instruction
                    ) or self._pointer_value_used_in_definition_could_be_modified_via_memory_access_between_definition_and_target(
                        definition, instruction
                    ):
                        continue
                    old_instr = str(instruction)
                    block, index = self._blocks_map.get(old_instr).pop()
                    instruction.substitute(var, definition.value.copy())
                    self._update_use_map(var, instruction)
                    self._update_block_map(old_instr, str(instruction), block, index)
