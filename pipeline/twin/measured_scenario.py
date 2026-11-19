"""Explicit measured-cell adapter and decision-only baseline replay (#45).

No SINR, load, HO execution success or throughput is fabricated. Unknown
identities/support stay unknown; no ocid cell is arbitrarily relabelled.
"""
import argparse
import hashlib
import json
import math
from collections import Counter,defaultdict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from .route_radio import RouteRadioMap,link_key,model_document,spatial_points
from .replay_reference import A3Batch
from .walktest_ingest import source_digest

ROOT=Path(__file__).resolve().parents[2]
REFERENCE_COMMIT="a98c2cc8fec977b5a4aaa0e8c457aeff222518c1"


def hash_file(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cell_name(key):return "/".join(map(str,key))


def build_mapping(train):
    """Only lap-1 serving identities establish candidate PCI/channel bindings."""
    keys=sorted({link_key(e) for e in train})
    bindings=defaultdict(set)
    for e in train:
        bindings[(e["rat"],e["mcc"],e["mnc"],e["pci"],e["earfcn"])].add(link_key(e))
    return dict(format="horus-measured-cell-mapping-v1",source_split="development only",
                cells=[dict(index=i,id=cell_name(k),key=list(k)) for i,k in enumerate(keys)],
                pci_channel_bindings=[dict(observed=list(k),candidates=[list(v) for v in sorted(vals)]) for k,vals in sorted(bindings.items())],
                caveat="Neighbours without PLMN use the serving PLMN as an explicit assumption; a unique PCI/channel binding is not independently verified neighbour identity.")


def resolve_neighbour(e,n,mapping):
    allowed={tuple(c["key"]) for c in mapping["cells"]}
    if n.get("rat")!=e["rat"] or n.get("earfcn") is None:return None,"unknown_rat_or_channel"
    full=n.get("cellid")
    if full is not None and 256<=full<268435455:
        key=(e["rat"],e["mcc"],e["mnc"],full,n["earfcn"])
        return (key,"full_id_with_assumed_serving_plmn") if key in allowed else (None,"full_id_unseen_in_training")
    observed=[e["rat"],e["mcc"],e["mnc"],n["pci"],n["earfcn"]]
    candidates={tuple(v) for b in mapping["pci_channel_bindings"] if b["observed"]==observed for v in b["candidates"]}
    if len(candidates)==1:return next(iter(candidates)),"unique_training_pci_channel_assumed_plmn"
    return None,"ambiguous_pci_channel" if len(candidates)>1 else "unknown_pci_channel"


def augment_training(train,mapping):
    links=[];counts=Counter()
    for e in train:
        if "joint_signal_tuple_review" not in e["flags"]:links.append(e)
        for n in e["neighbours"]:
            key,basis=resolve_neighbour(e,n,mapping);counts[basis]+=1
            if key is None:continue
            # Modem timestamp in a registered serving block cannot establish
            # a neighbour's acquisition time. Keep each as a source row.
            link=dict(e,cell=list(key[:4]),earfcn=key[4],rsrp=n["rsrp"],source_link=None,
                      row=f"{e['row']}:neighbour:{n['slot']}")
            links.append(link)
    return links,dict(counts)


def predict_matrix(rm,keys,x,y):
    """Vectorized equivalent of RouteRadioMap.predict; NaN means unsupported."""
    result=np.full((len(x),len(keys)),np.nan)
    params=rm.model["parameters"]
    for j,key in enumerate(keys):
        points=rm.points.get(tuple(key),[])
        if not points:continue
        px=np.array([p["x"] for p in points]);py=np.array([p["y"] for p in points]);v=np.array([p["rsrp"] for p in points])
        d=np.hypot(x[:,None]-px,y[:,None]-py)
        # Stable sorting preserves point-order tie behavior of scalar predict.
        order=np.argsort(d,axis=1,kind="stable")[:,:params["k"]]
        near=np.take_along_axis(d,order,axis=1);valid=near<=params["support_radius_m"]
        w=np.where(valid,1/np.maximum(near,1)**params["power"],0)
        supported=valid.sum(axis=1)>=params["minimum_points"]
        result[supported,j]=(w[supported]*v[order[supported]]).sum(axis=1)/w[supported].sum(axis=1)
    return result


def position_trace(epochs,dt):
    if not epochs:raise ValueError("Empty replay session")
    t=np.array([e["t"] for e in epochs]);elapsed=t-t[0]
    if np.any(np.diff(t)<=0):raise ValueError("Replay requires strictly increasing logger times")
    sample=np.arange(0,elapsed[-1]+1e-7,dt)
    x=np.interp(sample,elapsed,[e["x"] for e in epochs]);y=np.interp(sample,elapsed,[e["y"] for e in epochs])
    source=np.maximum(np.searchsorted(elapsed,sample,side="right")-1,0)
    right=np.minimum(source+1,len(t)-1)
    location_supported=(np.abs(sample-elapsed[source])<1e-7)|((elapsed[right]-elapsed[source])<=3)
    return sample,x,y,source,location_supported


def run_decisions(values,dt,controller="a3-stock"):
    """Counterfactual decision diagnostic, NOT the PHY execution simulator.

    Missing serving support triggers an explicit support reset/reattachment,
    separate from decisions. Both UEs/links are conceptual model states only.
    """
    configs={"a3-stock":dict(offset_db=3,hys_db=1,ttt_s=.32,l3_k=4),
             "a3-legacy-params":dict(offset_db=0,hys_db=3,ttt_s=3,l3_k=0)}
    cfg=configs.get(controller);policy=A3Batch(**cfg) if cfg else None
    if cfg is None and controller!="strongest":raise ValueError("Unsupported decision controller")
    k=cfg["l3_k"] if cfg else 0
    alpha=1-(1-2**(-k/4))**(dt/.2)
    serving=None;filtered=np.full(values.shape[1],np.nan);previous=None;last_change=-math.inf
    counts=Counter();signal=[];events=[];durations=Counter()
    for i,row in enumerate(values):
        available=np.isfinite(row);n=int(available.sum());durations[n]+=dt
        if not n:
            if serving is not None:counts["support_gaps"]+=1
            serving=None;previous=None;filtered[:]=np.nan
            if policy:policy.reset()
            continue
        present=np.isfinite(filtered)&available
        filtered[~available]=np.nan
        filtered[available&~present]=row[available&~present]
        filtered[present]=(1-alpha)*filtered[present]+alpha*row[present]
        forced=serving is None or not available[serving]
        if forced:
            serving=int(np.nanargmax(row));counts["support_attaches"]+=1;previous=None
            if policy:policy.reset()
        else:
            if policy:
                obs=SimpleNamespace(l3=np.where(available,filtered,-np.inf)[None,:],serving=np.array([serving]),
                                    active=available,can_ho=np.array([True]),dt=dt)
                target=int(policy.decide_batch(obs)[0][0])
            else:target=int(np.nanargmax(row))
            if target>=0 and target!=serving:
                if not available[target]:raise AssertionError("Controller targeted missing support")
                now=i*dt
                counts["switch_decisions"]+=1
                counts["returns_under_1s"]+=target==previous and now-last_change<1
                counts["returns_under_5s"]+=target==previous and now-last_change<5
                events.append(dict(t=now,source=int(serving),target=target,rsrp_source=float(row[serving]),rsrp_target=float(row[target])))
                previous,serving,last_change=serving,target,now
        signal.append(float(row[serving]))
    return dict(controller=controller,parameters=cfg,counts=dict(counts),
                supported_fraction=len(signal)/len(values),duration_by_supported_cells_s=dict(durations),
                mean_modelled_serving_rsrp=float(np.mean(signal)) if signal else None,
                ho_success_rate=None,rlf=None,throughput=None,
                note="Decisions applied instantaneously in an RSRP-only diagnostic. Support resets are not measured network failures. No execution or utility claim."),events


def fixture_preflight(path,mapping,root=ROOT):
    from jsonschema import Draft202012Validator
    doc=json.loads(Path(path).read_text(encoding="utf-8"));errors=list(Draft202012Validator(json.loads((root/"schemas/policy_artifact.schema.json").read_text())).iter_errors(doc))
    result=dict(fixture=Path(path).name,version=doc.get("version"),gate=(doc.get("gate")or{}).get("verdict"),eligible=False)
    if errors:return dict(result,reason="artifact_schema_invalid")
    if doc["gate"]["verdict"]!="promote":return dict(result,reason="gate_not_promoted")
    weight=(root/doc["weights_ref"]).resolve()
    if not weight.is_relative_to(root.resolve()) or not weight.is_file():return dict(result,reason="weights_missing_or_outside_repo")
    import torch
    ckpt=torch.load(weight,map_location="cpu",weights_only=True)
    expected=[c["id"] for c in mapping["cells"]]
    result.update(weights_sha256=hash_file(weight),trained_cells=ckpt.get("cells"),required_cells=expected)
    if ckpt.get("version")!=doc["version"]:return dict(result,reason="checkpoint_version_mismatch")
    if ckpt.get("cells")!=expected:return dict(result,reason="incompatible_cell_action_space")
    # Even matching cell labels would not by itself validate units/cadence or
    # missing features. Additional deployment qualification remains necessary.
    return dict(result,reason="requires_feature_and_units_qualification")


def native_fixture_smoke(path,root=ROOT):
    """Weight/inference health on original nine-site inputs, never campus inputs."""
    from .dqn import DQNController
    from .radio import opencellid_map
    doc=json.loads(Path(path).read_text(encoding="utf-8"))
    if doc["gate"]["verdict"]!="promote":return dict(status="skipped_rejected",decide_calls=0)
    controller=DQNController(root/doc["weights_ref"]);controller.reset();rm=opencellid_map(seed=0)
    expected=sorted(c.cell_id for c in rm.cells)
    if controller.cells!=expected:return dict(status="native_reference_space_mismatch",decide_calls=0)
    ue=SimpleNamespace(ue_id="native-fixture-smoke",serving=None)
    for i in range(12):
        signals=rm.measure(450+i*3,500)
        if ue.serving is None:ue.serving=max(signals,key=signals.get)
        action=controller.decide(ue,signals,i)
        if action is not None:
            if action not in expected:raise AssertionError("Native checkpoint emitted invalid target")
            ue.serving=action
    return dict(status="passed",decide_calls=12,input_provenance="original synthetic nine-site map, not measured campus",performance_claim=False)


def validate_reverse_links(test,mapping,rm):
    errors=defaultdict(list);attempted=Counter();unknown=0
    for e in test:
        links=[]
        if "joint_signal_tuple_review" not in e["flags"]:links.append(("serving",link_key(e),e["rsrp"]))
        for n in e["neighbours"]:
            key,_=resolve_neighbour(e,n,mapping)
            if key is None:unknown+=1
            else:links.append(("neighbor_assumed_identity",key,n["rsrp"]))
        for role,key,value in links:
            attempted[role]+=1;pred=rm.predict(key,e["x"],e["y"])
            if pred:errors[role].append(pred["rsrp"]-value)
    return dict(unresolved_neighbors=unknown,by_role={role:dict(attempted=count,supported=len(errors[role]),
                mae_db=float(np.mean(np.abs(errors[role]))) if errors[role] else None,
                p95_abs_db=float(np.percentile(np.abs(errors[role]),95)) if errors[role] else None) for role,count in attempted.items()},
                caveat="Conditional on reported links and unverified neighbor PLMN/PCI binding; not complete target coverage or independent-sample statistics.")


def prepare(dataset,model,out):
    dataset,model,out=Path(dataset),Path(model),Path(out);out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(l) for l in (dataset/"epochs.jsonl").read_text(encoding="utf-8").splitlines()]
    manifest=json.loads((dataset/"manifest.json").read_text(encoding="utf-8"))
    if hash_file(dataset/"epochs.jsonl")!=manifest["output_sha256"]["epochs.jsonl"]:raise ValueError("Dataset checksum mismatch")
    serving=json.loads(model.read_text(encoding="utf-8"))
    if serving["metadata"]["dataset_manifest_sha256"]!=hash_file(dataset/"manifest.json"):raise ValueError("Model/dataset mismatch")
    train=[e for e in rows if e["split"]=="development"]
    mapping=build_mapping(train);links,counts=augment_training(train,mapping)
    augmented=model_document(spatial_points(links),serving["parameters"],dict(serving["metadata"],
                                neighbor_identity_assumption=mapping["caveat"],training_link_rows=len(links),
                                purpose="Neighbour-augmented sensitivity; same frozen lap-1-selected parameters; no lap-2 fitting"))
    for name,data in [("cell-mapping.json",mapping),("neighbor-assumption-model.json",augmented)]:
        (out/name).write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8",newline="\n")
    audit=dict(cells=len(mapping["cells"]),training_neighbor_resolution=counts,serving_model_sha256=hash_file(model),
               neighbor_model_sha256=hash_file(out/"neighbor-assumption-model.json"),
               controller_reference_commit=REFERENCE_COMMIT,controller_source_sha256=source_digest(Path(__file__).with_name("replay_reference.py")),
               adapter_source_sha256=source_digest(__file__),dt_s=.1,
               limits="Registered modem time does not prove neighbour acquisition. PLMN assumption remains unverified. Unsupported cells are omitted, not filled. No SINR/HO-success model is claimed.")
    # Mapping and augmented model are frozen before inspecting reverse links.
    (out/"adapter-frozen.json").write_text(json.dumps(audit,indent=2)+"\n",encoding="utf-8",newline="\n")
    return rows,mapping,serving,augmented,audit


def run(dataset,model,out,dt=.1):
    out=Path(out);rows,mapping,serving,augmented,audit=prepare(dataset,model,out)
    keys=[tuple(c["key"]) for c in mapping["cells"]];reports=[];availability=[];reverse_neighbor=Counter();fallback_matrix=None
    for e in rows:
        if e["split"]=="evaluation":
            for n in e["neighbours"]:reverse_neighbor[resolve_neighbour(e,n,mapping)[1]]+=1
    for session in sorted({e["session"] for e in rows}):
        group=[e for e in rows if e["session"]==session]
        t,x,y,source,gps=position_trace(group,dt)
        for name,doc in [("serving_only",serving),("neighbor_assumption",augmented)]:
            matrix=predict_matrix(RouteRadioMap(doc),keys,x,y);matrix[~gps,:]=np.nan
            if session=="t4-reverse" and name=="neighbor_assumption":fallback_matrix=matrix
            availability.append(dict(session=session,variant=name,steps=len(t),any_support=float(np.mean(np.isfinite(matrix).any(axis=1))),
                                     competing_cells=float(np.mean(np.isfinite(matrix).sum(axis=1)>=2))))
            for spec in ("a3-stock","a3-legacy-params","strongest"):
                result,events=run_decisions(matrix,dt,spec);result.update(session=session,variant=name)
                reports.append(result)
                (out/f"{session}-{name}-{spec}-decisions.json").write_text(json.dumps(events,indent=2)+"\n",encoding="utf-8",newline="\n")
    fixtures=[fixture_preflight(p,mapping) for p in sorted((ROOT/"working/candidates").glob("*.json"))]
    # Verify fail-closed deployment actually executes a runnable baseline fixture.
    # These fallback runs share the exact frozen radio trace/baseline above.
    for f in fixtures:
        base,_=run_decisions(fallback_matrix,dt,"a3-stock")
        f["fallback_controller"]="a3-stock";f["fallback_switch_decisions"]=base["counts"].get("switch_decisions",0)
        f["ai_inference_calls"]=0
        f["native_space_smoke"]=native_fixture_smoke(ROOT/"working/candidates"/f["fixture"])
    link_validation=validate_reverse_links([e for e in rows if e["split"]=="evaluation"],mapping,RouteRadioMap(augmented))
    summary=dict(adapter=audit,availability=availability,reverse_neighbor_resolution=dict(reverse_neighbor),
                 runs=reports,policy_fixtures=fixtures,neighbor_surface_reverse_link_validation=link_validation,
                 verdict="Measured-route decision replay works; existing site-specific DQN artifacts are not deployable on this measured-cell mapping. No AI performance claim.")
    (out/"results.json").write_text(json.dumps(summary,indent=2)+"\n",encoding="utf-8",newline="\n")
    lines=["# Measured-route controller decision replay", "", summary["verdict"], "", "## Baselines", "",
           "Frozen A3Batch implementation from finals-twin a98c2cc. dt=0.1s; same interpolated measured positions and mean radio surface per arm. No fading, SINR, load, preparation/access or throughput is invented.",
           "", "| Session | Surface | Controller | Switch decisions | Support attaches | Mean modelled serving RSRP |", "|---|---|---|---:|---:|---:|"]
    for r in reports:
        lines.append(f"| {r['session']} | {r['variant']} | {r['controller']} | {r['counts'].get('switch_decisions',0)} | {r['counts'].get('support_attaches',0)} | {r['mean_modelled_serving_rsrp']:.2f} |")
    lines += ["", "## Boundary conditions", "", mapping["caveat"],
              "Serving-only and neighbor-augmented surfaces are separate sensitivity cases, not independently validated full radio fields. The reverse lap is the held-out route; forward replay is development/in-sample.",
              "Stock A3 uses offset 3 dB, hysteresis 1 dB, TTT 0.32s, L3 k=4; legacy parameter A3 uses offset 0, hysteresis 3, TTT 3s, k=0. Strongest is a no-hysteresis diagnostic, not an optimized deployment policy.",
              "Support attaches/gaps are map availability events, not real network failures. Switch counts and mean RSRP are modelled decisions, not observed handover success. A complete CHO execution/PHY evaluation requires additional assumptions/evidence and is not claimed here.",
              "", "## Policy fixtures", ""]
    for f in fixtures:lines.append(f"- {f['fixture']}: gate={f['gate']}, {f['reason']}; A3 fallback, no AI inference.")
    lines += ["", "Promoted checkpoints separately pass a 12-report load/inference smoke check in their original synthetic nine-site input space. Those calls are not part of the measured-campus replay and establish no performance gain.",
              "", "## Neighbor-augmented surface held-out link check", "", json.dumps(link_validation,indent=2)]
    (out/"REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8",newline="\n")
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("dataset","model","out"):p.add_argument("--"+name,required=True,type=Path)
    a=p.parse_args();r=run(a.dataset,a.model,a.out)
    print(json.dumps(dict(adapter=r["adapter"],availability=r["availability"],fixtures=r["policy_fixtures"]),indent=2))


if __name__=="__main__":main()
