from math import log2, floor
from os import name
from z3 import *
from .model import *


class GlobalInfo:
    def __init__(self, fp: Fixedpoint, 
            pods: List[PodAdapter], 
            policies: List[PolicyAdapter], 
            namespaces: List[NamespaceAdapter],
            check_self_ingress_traffic=True,
            check_select_by_no_policy=False):

        self.check_self_traffic = check_self_ingress_traffic
        self.check_select_by_any = check_select_by_no_policy

        self.rels: Dict[str, FuncDeclRef] = {}
        self.ns_rels: Dict[str, FuncDeclRef] = {}
        self.core_rels: Dict[str, FuncDeclRef] = {}
        self.lit_map: Dict[str, IntNumRef] = {}
        
        self.fp = fp
        
        self.namespaces = namespaces
        self.pods = pods
        self.policies = policies
        
        self.nam_map = {}
        for i, ns in enumerate(namespaces):
            self.nam_map[ns.name] = i
        
        self.nam_sort = BitVecSort(1 + floor(log2(1 + len(namespaces))))
        self.pod_sort = BitVecSort(1 + floor(log2(1 + len(pods))))
        self.pol_sort = BitVecSort(1 + floor(log2(1 + len(policies))))
        # XXX: this is a hack... assume less than 2^31 - 1 unique label valuess
        self.lv_sort = BitVecSort(32)
        self.lv_counter = 0

    def register_relation(self, name, func, is_core=False):
        self.fp.register_relation(func)
        if is_core:
            self.core_rels[name] = func
        else:
            self.rels[name] = func

    def register_relation_ns(self, name, func):
        self.fp.register_relation(func)
        self.ns_rels[name] = func

    def get_or_create_literal(self, s: str) -> Any:
        if s not in self.lit_map:
            self.lit_map[s] = BitVecVal(self.lv_counter, self.lv_sort)
            self.lv_counter += 1
        return self.lit_map[s]

    def get_relation(self, name) -> Optional[FuncDeclRef]:
        if name in self.rels:
            return self.rels[name]
        else:
            return None

    def get_relation_ns(self, name) -> Optional[FuncDeclRef]:
        if name in self.ns_rels:
            return self.ns_rels[name]
        else:
            return None

    def get_relation_core(self, name) -> Optional[FuncDeclRef]:
        if name in self.core_rels:
            return self.core_rels[name]
        else:
            return None

    def add_fact(self, fact, name=None):
        self.fp.fact(fact)

    def add_rule(self, lhs, rhs, name=None):
        self.fp.rule(lhs, rhs, name)

    def add_fact_call(self, name: str, *args, cname=None):
        func = self.rels[name]
        self.fp.fact(func(*args), name=cname)

    def add_fact_call_ns(self, name: str, *args, cname=None):
        func = self.ns_rels[name]
        self.fp.fact(func(*args), name=cname)

    def add_fact_call_core(self, name: str, *args, cname=None):
        func = self.core_rels[name]
        self.fp.fact(func(*args), name=cname)

    def pod_value(self, v: int) -> BitVecVal:
        return BitVecVal(v, self.pod_sort)

    def nam_value(self, v: int) -> BitVecVal:
        return BitVecVal(v, self.nam_sort)

    def pol_value(self, v: int) -> BitVecVal:
        return BitVecVal(v, self.pol_sort)

    def get_namespace_idx(self, ns: str) -> BitVecVal:
        return BitVecVal(self.nam_map[ns], self.nam_sort)

    def declare_var(self, name, sort, is_Var=False):
        if is_Var:
            var = Var(name, sort)
        else:
            var = Const(name, sort)
        self.fp.declare_var(var)
        return var


def get_fixpoint_engine(**kwargs) -> Fixedpoint:
    fp = Fixedpoint()
    fp_options = {
        "ctrl_c": True,
        "engine": "datalog",
        # FIXME: this must be set false to allow negation to be correctly dealt
        "datalog.generate_explanations": False,
    }
    fp_options.update(kwargs)
    fp.set(**fp_options)
    return fp


def get_datalog(fp: Fixedpoint, queries: List[Any]) -> str:
    return fp.to_string(queries)


def get_answer(fp: Fixedpoint, queries: List[Any]) -> Tuple[CheckSatResult, Any]:
    # TODO: parse the answer
    return (fp.query(queries), fp.get_answer())


def define_model(gi: GlobalInfo):
    # define is_pol/pod/nam helpers
    is_pol = Function('is_pol', gi.pol_sort, BoolSort())
    is_pod = Function('is_pod', gi.pod_sort, BoolSort())
    is_nam = Function('is_nam', gi.nam_sort, BoolSort())
    gi.register_relation('is_pol', is_pol, is_core=True)
    gi.register_relation('is_pod', is_pod, is_core=True)
    gi.register_relation('is_nam', is_nam, is_core=True)

    for i in range(len(gi.policies)):
        gi.add_fact(is_pol(gi.pol_value(i)))
    for i in range(len(gi.pods)):
        gi.add_fact(is_pod(gi.pod_value(i)))
    for i in range(len(gi.namespaces)):
        gi.add_fact(is_nam(gi.nam_value(i)))

    # define namespace(pod, value) relation
    namespace = Function('namespace', gi.pod_sort, gi.nam_sort, BoolSort())
    gi.register_relation("namespace", namespace, is_core=True)

    # define selected_by_pol(pod_index, pol_index)
    selected_by_pol = Function("selected_by_pol", gi.pod_sort, gi.pol_sort, BoolSort())
    gi.register_relation("selected_by_pol", selected_by_pol, is_core=True)

    selected_by_any = Function("selected_by_any", gi.pod_sort, BoolSort())
    gi.register_relation("selected_by_any", selected_by_any, is_core=True)

    selected_by_none = Function("selected_by_none", gi.pod_sort, BoolSort())
    gi.register_relation("selected_by_none", selected_by_none, is_core=True)

    # define ingress/egress_allow_by_pol(src_pod/dst_pod, pol)
    ingress_allow_by_pol = Function("ingress_allow_by_pol", gi.pod_sort, gi.pol_sort, BoolSort())
    gi.register_relation("ingress_allow_by_pol", ingress_allow_by_pol, is_core=True)

    egress_allow_by_pol = Function("egress_allow_by_pol", gi.pod_sort, gi.pol_sort, BoolSort())
    gi.register_relation("egress_allow_by_pol", egress_allow_by_pol, is_core=True)

    # define ingress/egress_traffic(src_pod/dst_pod, sel_pod)

    src = gi.declare_var('src', gi.pod_sort)
    dst = gi.declare_var('dst', gi.pod_sort)
    sel = gi.declare_var('sel', gi.pod_sort)
    pol = gi.declare_var('pol', gi.pol_sort)

    gi.add_rule(selected_by_any(sel), [
        is_pol(pol),
        selected_by_pol(sel, pol)
    ])

    gi.add_rule(selected_by_none(sel), [
        is_pod(sel),
        Not(selected_by_any(sel))
    ])

    ingress_traffic = Function("ingress_traffic", gi.pod_sort, gi.pod_sort, BoolSort())
    gi.register_relation("ingress_traffic", ingress_traffic, is_core=True)

    if gi.check_self_traffic:
        gi.add_rule(ingress_traffic(sel, sel), is_pod(sel))
    gi.add_rule(ingress_traffic(src, sel), [
        is_pod(sel),
        is_pod(src),
        selected_by_pol(sel, pol),
        is_pol(pol),
        ingress_allow_by_pol(src, pol)
    ])
    if gi.check_select_by_any:
        gi.add_rule(ingress_traffic(src, sel), [
            is_pod(src),
            is_pod(sel),
            selected_by_none(sel)
        ])

    egress_traffic = Function("egress_traffic", gi.pod_sort, gi.pod_sort, BoolSort())
    gi.register_relation("egress_traffic", egress_traffic, is_core=True)

    gi.add_rule(egress_traffic(dst, sel), [
        is_pod(sel),
        is_pod(dst),
        selected_by_pol(sel, pol),
        egress_allow_by_pol(dst, pol)
    ])
    if gi.check_select_by_any:
        gi.add_rule(egress_traffic(dst, sel), [
            is_pod(dst),
            is_pod(sel),
            selected_by_none(sel)
        ])

    edge = Function("edge", gi.pod_sort, gi.pod_sort, BoolSort())
    gi.register_relation("edge", edge, is_core=True)

    gi.add_rule(edge(src, dst), [
        ingress_traffic(src, sel),
        egress_traffic(dst, sel)
    ])

    path = Function("path", gi.pod_sort, gi.pod_sort, BoolSort())
    gi.register_relation("path", path, is_core=True)

    gi.add_rule(path(src, dst), edge(src, dst))
    gi.add_rule(path(src, dst), [edge(src, sel), edge(sel, dst)])

    # TODO: invariants?


def define_pod_facts(gi: GlobalInfo):
    """
    # FIXME: label conventions could overlap
    For label in pod -> define label function, add fact
        app: db -> app(pod_index, "db")
    For namespace in pod -> add namespace fact
        namespace: default -> namespace(pod_index, ns_idx)
    """
    for i, pod in enumerate(gi.pods):
        gi.add_fact_call_core("namespace", gi.pod_value(i), gi.get_namespace_idx(pod.namespace))

        for k, v in pod.labels.items():
            k_exists = "{}__exists".format(k)

            if gi.get_relation(k) is None:
                gi.register_relation(k, Function(k, gi.pod_sort, gi.lv_sort, BoolSort()))
            gi.add_fact_call(k, gi.pod_value(i), gi.get_or_create_literal(v))

            if gi.get_relation(k_exists) is None:
                gi.register_relation(k_exists, Function(k_exists, gi.pod_sort, BoolSort()))
            gi.add_fact_call(k_exists, gi.pod_value(i))

    for i, ns in enumerate(gi.namespaces):
        for k, v in ns.labels.items():
            k_ns = "{}__namespace".format(k)
            k_exists = "{}__exists".format(k_ns)

            if gi.get_relation_ns(k_ns) is None:
                gi.register_relation_ns(k_ns, Function(k, gi.nam_sort, gi.lv_sort, BoolSort()))
            gi.add_fact_call_ns(k_ns, gi.nam_value(i), gi.get_or_create_literal(v))

            if gi.get_relation_ns(k_exists) is None:
                gi.register_relation_ns(k_exists, Function(k_exists, gi.nam_sort, BoolSort()))
            gi.add_fact_call_ns(k_exists, gi.nam_value(i))


def define_pol_facts(gi: GlobalInfo):
    for i, pol in enumerate(gi.policies):
        pol.define_pod_selector(i, gi)
        pol.define_egress_rules(i, gi)
        pol.define_ingress_rules(i, gi)


def build(pods: List[PodAdapter], 
        pols: List[PolicyAdapter], 
        nams: List[NamespaceAdapter], 
        check_self_ingress_traffic=True, 
        check_select_by_no_policy=False, **kwargs):
    fp = get_fixpoint_engine(**kwargs)
    gi = GlobalInfo(fp, pods, pols, nams, 
        check_self_ingress_traffic=check_self_ingress_traffic, 
        check_select_by_no_policy=check_select_by_no_policy)

    define_model(gi)
    define_pod_facts(gi)
    define_pol_facts(gi)

    return gi