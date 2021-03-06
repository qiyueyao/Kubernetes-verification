"""
Kubernetes configuration files models
"""
from typing import *
from typing_extensions import *
from dataclasses import dataclass, field
from bitarray import bitarray
from abc import abstractmethod


@dataclass
class Container:
    name: str
    labels: Dict[str, str]

    select_policies: List[int] = field(default_factory=list)
    allow_policies: List[int] = field(default_factory=list)

    def getValueOrDefault(self, key: str, value: str):
        if key in self.labels:
            return self.labels[key]
        return value
    
    def getLabels(self):
        return self.labels


@dataclass
class PolicySelect:
    labels: Dict[str, str]


@dataclass
class PolicyAllow:
    labels: Dict[str, str]


@dataclass
class PolicyDirection:
    # true for ingression, false for egress
    direction: bool

    def is_ingress(self) -> bool:
        return self.direction

    def is_egress(self) -> bool:
        return not self.direction


PolicyIngress = PolicyDirection(True)
PolicyEgress = PolicyDirection(False)


@dataclass
class PolicyProtocol:
    protocols: List[str]


T = TypeVar('T')
class LabelRelation(Protocol[T]):
    @abstractmethod
    def match(self, rule: T, value: T) -> bool:
        raise NotImplementedError


class DefaultEqualityLabelRelation(LabelRelation):
    def match(self, rule: Any, value: Any) -> bool:
        return rule == value


@dataclass
class Policy:
    name: str
    selector: PolicySelect
    allow: PolicyAllow
    direction: PolicyDirection
    protocol: PolicyProtocol
    matcher: LabelRelation[str] = DefaultEqualityLabelRelation()
    working_select_set: bitarray = None
    working_allow_set: bitarray = None

    @property
    def working_selector(self):
        # FIXME: seems for ingress/egress, we can just swap allow/selector set
        if self.is_egress():
            return self.selector
        return self.allow

    @property
    def working_allow(self):
        if self.is_egress():
            return self.allow
        return self.selector

    def select_policy(self, container: Container) -> bool:
        cl = container.labels
        sl = self.working_selector.labels
        for k, v in cl.items():
            if k in sl.keys() and \
                not self.matcher.match(sl[k], v):
                return False
        return True

    def allow_policy(self, container: Container) -> bool:
        cl = container.labels
        al = self.working_allow.labels
        for k, v in cl.items():
            if k in al.keys() and \
                not self.matcher.match(al[k], v):
                return False
        return True

    def is_ingress(self):
        return self.direction.is_ingress()

    def is_egress(self):
        return self.direction.is_egress()

    def store_bcp(self, select_set: bitarray, allow_set: bitarray):
        self.working_select_set = select_set
        self.working_allow_set = allow_set


class ReachabilityMatrix:
    @staticmethod
    def build_matrix(containers: List[Container], policies: List[Policy]):
        n_container = len(containers)
        labelMap: Dict[str, bitarray] = DefaultDict(lambda: bitarray('0' * n_container))
        matrix = [bitarray('0' * n_container) for _ in range(n_container)]

        for i, container in enumerate(containers):
            for key, value in container.labels.items():
                labelMap[key][i] = True

        for i, policy in enumerate(policies):
            select_set = bitarray(n_container)
            select_set.setall(True)
            allow_set = bitarray(n_container)
            allow_set.setall(True)

            # work as all direction being egress
            for k, v in policy.working_selector.labels.items():
                if k in labelMap.keys():
                    select_set &= labelMap[k]
            for k, v in policy.working_allow.labels.items():
                if k in labelMap.keys():
                    allow_set &= labelMap[k]
            
            # dealing with not matched values (needs a customized predicate)
            for idx in range(n_container):
                if select_set[idx] and not policy.select_policy(containers[idx]):
                    select_set[idx] = False
                if allow_set[idx] and not policy.allow_policy(containers[idx]):
                    allow_set[idx] = False
            
            policy.store_bcp(select_set, allow_set)

            for idx in range(n_container):
                if select_set[idx]:
                    matrix[idx] |= allow_set
                    containers[idx].select_policies.append(i)
                if allow_set[idx]:
                    containers[idx].allow_policies.append(i)

        return ReachabilityMatrix(n_container, matrix)

    def __init__(self, container_size: int, matrix: Any) -> None:
        self.container_size = container_size
        self.matrix = matrix

    def __setitem__(self, key, value):
        self.matrix[key[0]][key[1]] = value
    
    def __getitem__(self, key):
        return self.matrix[key[0]][key[1]]

    def getrow(self, index):
        return self.matrix[index]

    def getcol(self, index):
        value = bitarray(self.container_size)
        for i in range(self.container_size):
            value[i] = self.matrix[i][index]
        return value
