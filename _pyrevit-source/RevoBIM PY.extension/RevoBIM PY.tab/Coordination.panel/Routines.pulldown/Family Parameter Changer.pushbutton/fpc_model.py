# -*- coding: utf-8 -*-
"""RevoBIM PY - Family Parameter Changer - reading families and their
parameters out of the *project* document.

Nothing here opens a family for editing - that only happens in fpc_ops
when a change is actually applied.

Two things keep this fast on a large model:

- **Type parameters are read from one symbol per family, not every
  symbol.** Family parameters are defined at the family level; every type
  of a family carries exactly the same set. Reading all of them was
  multiplying the work by the number of types for no new information.
- **Instances are walked once for the whole project, keyed by type id.**
  `GetTypeId()` is a cheap call; `Symbol.Family.Id` is two element
  lookups. A dictionary from symbol id to family id turns the per-instance
  cost into one dictionary hit, and the first instance found per family
  is the only one kept.
"""
import fpc_clr  # noqa - assemblies referenced before anything below

from fpc_core import eid_value


def _param_row(param, is_type):
    try:
        name = param.Definition.Name
    except Exception:
        return None
    is_shared = False
    guid = u''
    try:
        is_shared = bool(param.IsShared)
        if is_shared:
            guid = param.GUID.ToString()
    except Exception:
        is_shared = False
    try:
        storage = str(param.StorageType)
    except Exception:
        storage = u''
    return {
        'name': name,
        'is_type': is_type,
        'is_shared': is_shared,
        'guid': guid,
        'storage': storage,
    }


def _first_symbol(doc, fam):
    try:
        for sid in fam.GetFamilySymbolIds():
            sym = doc.GetElement(sid)
            if sym is not None:
                return sym
    except Exception:
        pass
    return None


def _editability(fam):
    """Why a family cannot be rebound, or None if it can. In-place
    families cannot go through EditFamily at all, and a family Revit
    reports as not editable will refuse it too."""
    try:
        if fam.IsInPlace:
            return u'in-place family'
    except Exception:
        pass
    try:
        if not fam.IsEditable:
            return u'not editable'
    except Exception:
        pass
    return None


def _build_family(doc, fam, sample_inst):
    try:
        if fam.FamilyCategory is not None:
            cat_name = fam.FamilyCategory.Name
        else:
            cat_name = u'Uncategorized'
    except Exception:
        cat_name = u'Uncategorized'

    sym = _first_symbol(doc, fam)
    if sym is None:
        return None

    type_params = {}
    try:
        for p in sym.Parameters:
            row = _param_row(p, True)
            if row is not None and row['name'] not in type_params:
                type_params[row['name']] = row
    except Exception:
        pass

    inst_params = {}
    if sample_inst is not None:
        try:
            for p in sample_inst.Parameters:
                row = _param_row(p, False)
                if row is None:
                    continue
                if row['name'] in type_params or row['name'] in inst_params:
                    continue
                inst_params[row['name']] = row
        except Exception:
            pass

    rows = list(type_params.values()) + list(inst_params.values())
    rows.sort(key=lambda r: r['name'].lower())

    return {
        'id': fam.Id,
        'key': eid_value(fam.Id),
        'name': fam.Name,
        'category': cat_name,
        'sample_instance_id': sample_inst.Id if sample_inst is not None else None,
        'blocked': _editability(fam),
        'params': rows,
    }


def _sample_instances(doc, families):
    """One pass over every FamilyInstance in the project, returning
    {family_key: instance} with the first instance seen per family."""
    from Autodesk.Revit.DB import FilteredElementCollector, FamilyInstance

    symbol_to_family = {}
    for fam in families:
        fam_key = eid_value(fam.Id)
        try:
            for sid in fam.GetFamilySymbolIds():
                symbol_to_family[eid_value(sid)] = fam_key
        except Exception:
            continue

    wanted = len(set(symbol_to_family.values()))
    found = {}
    if wanted == 0:
        return found
    try:
        for inst in FilteredElementCollector(doc).OfClass(FamilyInstance):
            try:
                fam_key = symbol_to_family.get(eid_value(inst.GetTypeId()))
            except Exception:
                continue
            if fam_key is None or fam_key in found:
                continue
            found[fam_key] = inst
            if len(found) >= wanted:
                break
    except Exception:
        pass
    return found


def scan_families(doc):
    """Returns a list of family dicts sorted by category then name."""
    from Autodesk.Revit.DB import FilteredElementCollector, Family

    raw = list(FilteredElementCollector(doc).OfClass(Family))
    samples = _sample_instances(doc, raw)

    families = []
    for fam in raw:
        entry = _build_family(doc, fam, samples.get(eid_value(fam.Id)))
        if entry is not None:
            families.append(entry)

    families.sort(key=lambda f: (f['category'].lower(), f['name'].lower()))
    return families


def rescan(doc, families, keys):
    """Re-reads only the families whose keys are given and returns a new
    list with those entries replaced in place. After a run this is the
    difference between re-reading three families and re-reading the
    whole project."""
    from Autodesk.Revit.DB import FilteredElementCollector, FamilyInstance

    wanted = set(keys)
    refreshed = {}
    for entry in families:
        if entry['key'] not in wanted:
            continue
        fam = doc.GetElement(entry['id'])
        if fam is None:
            refreshed[entry['key']] = None
            continue
        sample = None
        sid = entry.get('sample_instance_id')
        if sid is not None:
            sample = doc.GetElement(sid)
        if sample is None:
            # the previous sample may have been deleted; look again cheaply
            try:
                own_symbols = set(eid_value(s) for s in fam.GetFamilySymbolIds())
                for inst in FilteredElementCollector(doc).OfClass(FamilyInstance):
                    if eid_value(inst.GetTypeId()) in own_symbols:
                        sample = inst
                        break
            except Exception:
                sample = None
        refreshed[entry['key']] = _build_family(doc, fam, sample)

    return merge_families(families, refreshed)


def merge_families(families, refreshed):
    """Pure merge: entries whose key is in `refreshed` are replaced by the
    refreshed entry, or dropped if it is None. Order is kept. Tested on
    the bench without Revit."""
    out = []
    for entry in families:
        key = entry['key']
        if key in refreshed:
            replacement = refreshed[key]
            if replacement is not None:
                out.append(replacement)
        else:
            out.append(entry)
    return out
