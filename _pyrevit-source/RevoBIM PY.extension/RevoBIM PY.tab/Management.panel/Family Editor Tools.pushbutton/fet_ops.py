# =========================================================================
# Family Editor Tools - every write
#
# One transaction per run, with an IFailuresPreprocessor deleting warnings,
# and a per item SubTransaction so one refusal does not lose the batch.
# A void API call is not evidence: every create is read back.
#
# The window is modeless, so nothing in here may be called directly from a
# handler - it all goes out through the ExternalEvent at the bottom.
# =========================================================================

import fet_clr  # noqa: F401  - assemblies first, always

import os
import traceback

from System.Collections.Generic import List

from Autodesk.Revit.DB import (Color, CopyPasteOptions,
                               FilteredElementCollector, DuplicateTypeAction,
                               ElementId, ElementTransformUtils,
                               FailureProcessingResult, GraphicsStyleType,
                               IDuplicateTypeNamesHandler,
                               IFailuresPreprocessor, Line, Material,
                               Reference, ReferenceArray, SubTransaction,
                               Transaction, TransactionGroup,
                               TransactionStatus, Transform, XYZ)
from Autodesk.Revit.UI import ExternalEvent, IExternalEventHandler

import fet_core
import fet_model
import fet_planes

# Set for the length of a diagnostic run.  Everything on the appearance
# asset path reports through it, so a run that fails can be described
# rather than guessed at.
TRACE = None


def _trace(text, indent=1):
    if TRACE is not None:
        TRACE.note(text, indent)


def _trace_fail(what, indent=1):
    if TRACE is not None:
        TRACE.fail(what, traceback.format_exc(), indent)


CREATED = u"created"
EXISTING = u"existing"
FAILED = u"failed"
SKIPPED = u"skipped"


class Result(object):
    def __init__(self, status, subject, message=u""):
        self.status = status
        self.subject = subject
        self.message = message

    def __repr__(self):
        return u"<{0} {1}: {2}>".format(self.status, self.subject, self.message)


def counts(results):
    out = {CREATED: 0, EXISTING: 0, FAILED: 0, SKIPPED: 0}
    for item in results or []:
        if item.status in out:
            out[item.status] += 1
    return out


def needs_a_look(results):
    tally = counts(results)
    return tally[FAILED] > 0 or tally[SKIPPED] > 0


def summary_line(results):
    tally = counts(results)
    bits = []
    if tally[CREATED]:
        bits.append(u"{0} created".format(tally[CREATED]))
    if tally[EXISTING]:
        bits.append(u"{0} already there".format(tally[EXISTING]))
    if tally[SKIPPED]:
        bits.append(u"{0} skipped".format(tally[SKIPPED]))
    if tally[FAILED]:
        bits.append(u"{0} refused".format(tally[FAILED]))
    if not bits:
        return u"Nothing to do"
    return u", ".join(bits)


# =========================================================================
# Transactions
# =========================================================================

class WarningSwallower(IFailuresPreprocessor):
    def PreprocessFailures(self, accessor):
        try:
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return FailureProcessingResult.Continue


def _start(doc, name):
    transaction = Transaction(doc, name)
    transaction.Start()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(WarningSwallower())
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    return transaction


def _commit(transaction, results):
    u"""Transaction.Commit() returns a status.  Check it rather than
    assuming a call that did not throw did the work."""
    try:
        status = transaction.Commit()
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        results.append(Result(FAILED, u"the transaction",
                              u"Revit refused to commit: {0}".format(
                                  traceback.format_exc().strip().splitlines()[-1])))
        return False
    if status != TransactionStatus.Committed:
        results.append(Result(FAILED, u"the transaction",
                              u"the transaction ended as {0}".format(status)))
        return False
    return True


def _isolated(function, *args):
    u"""Run one item in its own SubTransaction so a refusal costs that item
    and nothing else in the batch."""
    doc = args[0]
    sub = SubTransaction(doc)
    sub.Start()
    try:
        result = function(*args)
        sub.Commit()
        return result
    except Exception:
        try:
            sub.RollBack()
        except Exception:
            pass
        raise


def _last_line(text):
    lines = [line for line in fet_core._as_text(text).strip().splitlines() if line.strip()]
    return lines[-1] if lines else u"Revit refused it and said nothing"


# =========================================================================
# Shared parameters
# =========================================================================

def _open_definition_file(app, path):
    u"""Setting SharedParametersFilename changes a Revit setting the user
    did not ask to change, so the old value is put back afterwards by the
    caller.  The listing is read from the file as text elsewhere; this is
    only used at the moment of adding, because AddParameter needs a live
    ExternalDefinition."""
    previous = u""
    try:
        previous = app.SharedParametersFilename or u""
    except Exception:
        previous = u""
    app.SharedParametersFilename = path
    return app.OpenSharedParameterFile(), previous


def _definitions_by_guid(definition_file):
    out = {}
    if definition_file is None:
        return out
    try:
        groups = list(definition_file.Groups)
    except Exception:
        return out
    for group in groups:
        try:
            definitions = list(group.Definitions)
        except Exception:
            continue
        for definition in definitions:
            try:
                out[u"{0}".format(definition.GUID).lower()] = definition
            except Exception:
                continue
    return out


def _add_one_parameter(doc, definition, group_option, is_instance):
    manager = doc.FamilyManager
    if group_option is not None:
        try:
            return manager.AddParameter(definition, group_option.value, is_instance)
        except Exception:
            pass
    # Whichever group family the release does not want, try the other one
    # with a safe default rather than losing the parameter over its group.
    for option in fet_model.group_options():
        if option.label.lower() in (u"data", u"other", u"general"):
            try:
                return manager.AddParameter(definition, option.value, is_instance)
            except Exception:
                continue
    raise Exception(u"AddParameter refused every group this release offers")


def _replace_one_parameter(doc, existing, definition, group_option,
                           is_instance):
    u"""ReplaceParameter keeps the formulas, labels and values that pointed
    at the old parameter, which is the whole reason to swap rather than add
    and delete."""
    manager = doc.FamilyManager
    target = manager.get_Parameter(existing.name)
    if target is None:
        raise Exception(u"'{0}' is no longer in the family".format(
            existing.name))
    if group_option is not None:
        return manager.ReplaceParameter(target, definition,
                                        group_option.value, is_instance)
    raise Exception(u"no parameter group this release will take")


def add_shared_parameters(doc, app, spf_path, rows, settings):
    u"""rows are fet_core.TemplateRow.  Returns a list of Result."""
    results = []
    if not fet_model.is_family(doc):
        results.append(Result(FAILED, u"the document",
                              u"this is not a family document"))
        return results
    if not rows:
        results.append(Result(SKIPPED, u"the selection", u"nothing was ticked"))
        return results

    try:
        definition_file, previous = _open_definition_file(app, spf_path)
    except Exception:
        results.append(Result(FAILED, spf_path,
                              u"the shared parameter file would not open: {0}".format(
                                  _last_line(traceback.format_exc()))))
        return results

    try:
        definitions = _definitions_by_guid(definition_file)
        by_name, by_guid = fet_model.existing_parameter_index(doc)

        transaction = _start(doc, u"RevoBIM - add shared parameters")
        for row in rows:
            guid = fet_core._as_text(row.guid).lower()
            definition = definitions.get(guid)
            if definition is None:
                results.append(Result(FAILED, row.name,
                                      u"that GUID is not in the chosen file"))
                continue
            group_option = fet_model.group_by_key(row.group)

            if row.replaces:
                existing = by_name.get(row.target.lower())
                if existing is None:
                    results.append(Result(FAILED, row.name,
                                          u"'{0}' is not in the family to "
                                          u"replace".format(row.target)))
                    continue
                clash = by_name.get(row.name.lower())
                if clash is not None and clash.name.lower() != row.target.lower():
                    results.append(Result(SKIPPED, row.name,
                                          u"another parameter already has "
                                          u"that name"))
                    continue
                if existing.is_builtin:
                    results.append(Result(SKIPPED, row.name,
                                          u"'{0}' is a built-in parameter and "
                                          u"cannot be replaced".format(
                                              row.target)))
                    continue
                try:
                    _isolated(_replace_one_parameter, doc, existing,
                              definition, group_option, row.is_instance)
                except Exception:
                    results.append(Result(FAILED, row.name,
                                          _last_line(traceback.format_exc())))
                    continue
                note = u"replaced '{0}', kept as {1}".format(
                    row.target, u"instance" if row.is_instance else u"type")
                if not fet_core.swap_is_clean(row.data_type,
                                              existing.data_type):
                    note += u" - {0} for {1}, so anything that referred to it "
                    note = note.format(existing.data_type or u"?",
                                       row.data_type or u"?")
                    note += u"may not have survived"
                results.append(Result(CREATED, row.name, note))
                continue

            if guid in by_guid:
                results.append(Result(EXISTING, row.name,
                                      u"already in the family as '{0}'".format(
                                          by_guid[guid].name)))
                continue
            if row.name.lower() in by_name:
                results.append(Result(SKIPPED, row.name,
                                      u"a different parameter of that name is "
                                      u"already in the family - set the row to "
                                      u"replace it if that is what you want"))
                continue
            try:
                _isolated(_add_one_parameter, doc, definition,
                          group_option, row.is_instance)
            except Exception:
                results.append(Result(FAILED, row.name,
                                      _last_line(traceback.format_exc())))
                continue
            results.append(Result(CREATED, row.name, u"{0}, under {1}".format(
                u"instance" if row.is_instance else u"type",
                group_option.label if group_option else u"the default group")))

        if _commit(transaction, results):
            # Prove it landed.  Revit does not reliably raise when a write
            # does not take.
            after_name, after_guid = fet_model.existing_parameter_index(doc)
            for item in results:
                if item.status != CREATED:
                    continue
                if item.subject.lower() not in after_name:
                    item.status = FAILED
                    item.message = u"the call was accepted but the parameter " \
                                   u"is not in the family afterwards"
    finally:
        try:
            app.SharedParametersFilename = previous
        except Exception:
            pass
    return results


# =========================================================================
# Editing the family's own parameters
# =========================================================================

def _set_group(param, group_option):
    u"""There is no one call that moves a family parameter's group across
    2024 to 2027, so both routes are tried and a release that takes
    neither is reported rather than silently doing nothing."""
    if group_option is None:
        return False, u"no group was chosen"
    definition = param.Definition
    if group_option.is_forge:
        try:
            definition.SetGroupTypeId(group_option.value)
            return True, u""
        except Exception:
            pass
    try:
        definition.ParameterGroup = group_option.value
        return True, u""
    except Exception:
        pass
    return False, u"this release will not move a parameter's group"


def apply_parameter_edits(doc, edits):
    u"""edits are fet_core.ParamEdit, keyed to the parameter's current
    name.  Every parameter is looked up again INSIDE the transaction, never
    from a handle the window captured."""
    results = []
    if not fet_model.is_family(doc):
        return [Result(FAILED, u"the document", u"this is not a family document")]
    live = [edit for edit in edits if edit.touches_anything()]
    if not live:
        return [Result(SKIPPED, u"the table", u"nothing is waiting to be applied")]

    before = fet_model.family_parameters(doc)
    by_name = dict([(row.name.lower(), row) for row in before])
    all_names = [row.name for row in before]

    steps, problems = fet_core.plan_renames(
        [(edit.current, edit.new_name) for edit in live if edit.renames],
        all_names)
    for problem in problems:
        results.append(Result(FAILED, u"a rename", problem))
    if problems:
        return results

    manager = doc.FamilyManager
    transaction = _start(doc, u"RevoBIM - edit family parameters")

    # ----- everything but the names, while the names still match -----
    for edit in live:
        record = by_name.get(edit.current.lower())
        if record is None:
            results.append(Result(FAILED, edit.current,
                                  u"it is no longer in the family"))
            continue
        if record.is_builtin and (edit.renames or edit.group is not None or
                                  edit.binding is not None):
            results.append(Result(SKIPPED, edit.current,
                                  u"a built-in parameter cannot be renamed, "
                                  u"regrouped or rebound"))
            continue
        param = manager.get_Parameter(edit.current)
        if param is None:
            results.append(Result(FAILED, edit.current,
                                  u"Revit will not hand it back by name"))
            continue
        changed = []

        if edit.binding is not None and edit.binding != record.binding:
            try:
                if edit.binding == u"instance":
                    _isolated(_make_instance, doc, manager, param)
                else:
                    _isolated(_make_type, doc, manager, param)
                changed.append(edit.binding)
            except Exception:
                results.append(Result(FAILED, edit.current,
                                      _last_line(traceback.format_exc())))
                continue
            param = manager.get_Parameter(edit.current)

        if edit.group is not None and edit.group != record.group_key:
            option = fet_model.group_by_key(edit.group)
            ok, why = _set_group(param, option)
            if ok:
                changed.append(option.label if option else edit.group)
            else:
                results.append(Result(FAILED, edit.current, why))
                continue

        if edit.formula is not None and edit.formula != record.formula:
            text = fet_core._as_text(edit.formula).strip()
            try:
                _isolated(_set_formula, doc, manager, param,
                          text if text else None)
                changed.append(u"formula" if text else u"formula cleared")
            except Exception:
                results.append(Result(FAILED, edit.current,
                                      u"the formula was refused: {0}".format(
                                          _last_line(traceback.format_exc()))))
                continue

        if changed:
            results.append(Result(CREATED, edit.current, u", ".join(changed)))

    # ----- then the names, in the planned order -----
    for source, target in steps:
        param = manager.get_Parameter(source)
        if param is None:
            results.append(Result(FAILED, source, u"it is no longer there"))
            continue
        try:
            _isolated(_rename, doc, manager, param, target)
        except Exception:
            results.append(Result(FAILED, source,
                                  _last_line(traceback.format_exc())))
            continue
        if not target.startswith(fet_core.PARK_PREFIX):
            results.append(Result(CREATED, target,
                                  u"renamed from '{0}'".format(source)
                                  if not source.startswith(fet_core.PARK_PREFIX)
                                  else u"renamed"))

    if _commit(transaction, results):
        after = set([row.name.lower() for row in fet_model.family_parameters(doc)])
        for edit in live:
            if not edit.renames:
                continue
            if edit.new_name.lower() not in after:
                results.append(Result(FAILED, edit.new_name,
                                      u"the rename was accepted but the "
                                      u"parameter is not there afterwards"))
    return results


def _make_instance(doc, manager, param):
    return manager.MakeInstance(param)


def _make_type(doc, manager, param):
    return manager.MakeType(param)


def _set_formula(doc, manager, param, text):
    return manager.SetFormula(param, text)


def _rename(doc, manager, param, name):
    return manager.RenameParameter(param, name)

# =========================================================================
# Materials
# =========================================================================

def _set_material_pattern(doc, material, name, patterns, is_cut):
    if not name:
        return
    pattern_id = patterns.get(fet_core._as_text(name).lower())
    if pattern_id is None:
        return
    if is_cut:
        order = (u"CutForegroundPatternId", u"CutPatternId")
    else:
        order = (u"SurfaceForegroundPatternId", u"SurfacePatternId")
    for attribute in order:
        try:
            setattr(material, attribute, pattern_id)
            return
        except Exception:
            continue


def _create_one_material(doc, preset, patterns):
    element_id = Material.Create(doc, preset.name)
    material = doc.GetElement(element_id)
    rgb = fet_core.parse_colour(preset.get(u"colour"))
    if rgb:
        try:
            material.Color = Color(rgb[0], rgb[1], rgb[2])
        except Exception:
            pass
    for attribute, key in ((u"Transparency", u"transparency"),
                           (u"Shininess", u"shininess")):
        raw = preset.get(key)
        if raw == u"":
            continue
        try:
            setattr(material, attribute, int(fet_core.to_number(raw, 0)))
        except Exception:
            pass
    klass = preset.get(u"class")
    if klass:
        try:
            material.MaterialClass = klass
        except Exception:
            pass
    _set_material_pattern(doc, material, preset.get(u"surface_pattern"),
                          patterns, False)
    _set_material_pattern(doc, material, preset.get(u"cut_pattern"),
                          patterns, True)
    return element_id


def create_materials(doc, presets, overwrite=False):
    results = []
    if not presets:
        return [Result(SKIPPED, u"materials", u"nothing was ticked")]
    existing = {}
    for name, element_id in fet_model.materials(doc):
        existing[name.lower()] = element_id
    patterns = fet_model.fill_patterns(doc)
    transaction = _start(doc, u"RevoBIM - load materials")
    for preset in presets:
        if preset.name.lower() in existing:
            results.append(Result(EXISTING, preset.name,
                                  u"a material of that name is already here"))
            continue
        try:
            _isolated(_create_one_material, doc, preset, patterns)
        except Exception:
            results.append(Result(FAILED, preset.name,
                                  _last_line(traceback.format_exc())))
            continue
        results.append(Result(CREATED, preset.name, preset.get(u"colour")))
    if _commit(transaction, results):
        after = set([name.lower() for name in fet_model.material_names(doc)])
        for item in results:
            if item.status == CREATED and item.subject.lower() not in after:
                item.status = FAILED
                item.message = u"accepted, but the material is not in the family"
    return results


# =========================================================================
# Line styles and subcategories
# =========================================================================

def _create_one_subcategory(doc, category, preset, patterns):
    sub = doc.Settings.Categories.NewSubcategory(category, preset.name)
    weight = int(fet_core.to_number(preset.get(u"weight"), 1))
    if weight > 0:
        try:
            sub.SetLineWeight(weight, GraphicsStyleType.Projection)
        except Exception:
            pass
        try:
            sub.SetLineWeight(weight, GraphicsStyleType.Cut)
        except Exception:
            pass
    rgb = fet_core.parse_colour(preset.get(u"colour"))
    if rgb:
        try:
            sub.LineColor = Color(rgb[0], rgb[1], rgb[2])
        except Exception:
            pass
    pattern = fet_core._as_text(preset.get(u"pattern")).lower()
    if pattern:
        pattern_id = patterns.get(pattern)
        if pattern_id is not None:
            try:
                sub.SetLinePatternId(pattern_id, GraphicsStyleType.Projection)
            except Exception:
                pass
    return sub


def create_line_styles(doc, presets):
    u"""A preset marked 'subcategory' goes on the family's own category
    instead of Lines - in a family both are made the same way, and both
    are needed."""
    results = []
    if not presets:
        return [Result(SKIPPED, u"line styles", u"nothing was ticked")]
    lines_category = fet_model.lines_category(doc)
    own_category = fet_model.own_category(doc)
    existing_lines = set([n.lower() for n in fet_model.line_style_names(doc)])
    existing_own = set([n.lower() for n in fet_model.family_subcategory_names(doc)])
    patterns = fet_model.line_patterns(doc)
    transaction = _start(doc, u"RevoBIM - load line styles")
    for preset in presets:
        scope = fet_core._as_text(preset.get(u"scope")).lower() or u"lines"
        if scope == u"subcategory":
            category = own_category
            already = existing_own
            where = fet_model.family_category_name(doc) or u"the family category"
        else:
            category = lines_category
            already = existing_lines
            where = u"Lines"
        if category is None:
            results.append(Result(SKIPPED, preset.name,
                                  u"{0} has no subcategories in this "
                                  u"family".format(where)))
            continue
        if preset.name.lower() in already:
            results.append(Result(EXISTING, preset.name,
                                  u"already under {0}".format(where)))
            continue
        try:
            _isolated(_create_one_subcategory, doc, category, preset, patterns)
        except Exception:
            results.append(Result(FAILED, preset.name,
                                  _last_line(traceback.format_exc())))
            continue
        already.add(preset.name.lower())
        results.append(Result(CREATED, preset.name, u"under {0}".format(where)))
    if _commit(transaction, results):
        after = set([n.lower() for n in fet_model.line_style_names(doc)])
        after.update([n.lower() for n in fet_model.family_subcategory_names(doc)])
        for item in results:
            if item.status == CREATED and item.subject.lower() not in after:
                item.status = FAILED
                item.message = u"accepted, but the subcategory is not there"
    return results


# =========================================================================
# Annotation styles
#
# A TextNoteType cannot be made from nothing, so one is duplicated and its
# parameters set.  Duplicate() is on ElementType and has been there since
# well before 2024, which is what makes it the safe route.
# =========================================================================

def _set_param(element, name, value, as_length_mm=False):
    member = fet_model.bip(name)
    if member is None:
        return False
    try:
        parameter = element.get_Parameter(member)
    except Exception:
        parameter = None
    if parameter is None or parameter.IsReadOnly:
        return False
    try:
        if as_length_mm:
            return bool(parameter.Set(fet_core.mm_to_ft(value)))
        return bool(parameter.Set(value))
    except Exception:
        return False


def _create_one_text_type(doc, source, preset, arrowheads):
    new_type = source.Duplicate(preset.name)
    _set_param(new_type, u"TEXT_FONT", preset.get(u"font") or u"Arial")
    _set_param(new_type, u"TEXT_SIZE",
               fet_core.to_number(preset.get(u"size_mm"), 2.5), True)
    _set_param(new_type, u"TEXT_STYLE_BOLD",
               1 if preset.get(u"bold") == u"1" else 0)
    _set_param(new_type, u"TEXT_STYLE_ITALIC",
               1 if preset.get(u"italic") == u"1" else 0)
    _set_param(new_type, u"TEXT_STYLE_UNDERLINE",
               1 if preset.get(u"underline") == u"1" else 0)
    width = fet_core.to_number(preset.get(u"width_factor"), 1.0)
    if width > 0:
        _set_param(new_type, u"TEXT_WIDTH_SCALE", width)
    _set_param(new_type, u"TEXT_BACKGROUND",
               1 if preset.get(u"background") == u"1" else 0)
    arrow = arrowheads.get(fet_core._as_text(preset.get(u"arrowhead")).lower())
    if arrow is not None:
        _set_param(new_type, u"LEADER_ARROWHEAD", arrow)
    return new_type


def create_text_types(doc, presets):
    results = []
    if not presets:
        return [Result(SKIPPED, u"text types", u"nothing was ticked")]
    types = fet_model.text_note_types(doc)
    if not types:
        return [Result(FAILED, u"text types",
                       u"this family carries no text type to duplicate from")]
    source = doc.GetElement(types[0][1])
    existing = set([name.lower() for name, element_id in types])
    arrowheads = {}
    for name, element_id in fet_model.arrowhead_names(doc):
        arrowheads[name.lower()] = element_id
    transaction = _start(doc, u"RevoBIM - load text types")
    for preset in presets:
        if preset.name.lower() in existing:
            results.append(Result(EXISTING, preset.name, u"already here"))
            continue
        try:
            _isolated(_create_one_text_type, doc, source, preset, arrowheads)
        except Exception:
            results.append(Result(FAILED, preset.name,
                                  _last_line(traceback.format_exc())))
            continue
        existing.add(preset.name.lower())
        results.append(Result(CREATED, preset.name,
                              u"{0}mm {1}".format(preset.get(u"size_mm"),
                                                  preset.get(u"font"))))
    if _commit(transaction, results):
        after = set([name.lower() for name, element_id
                     in fet_model.text_note_types(doc)])
        for item in results:
            if item.status == CREATED and item.subject.lower() not in after:
                item.status = FAILED
                item.message = u"accepted, but the text type is not there"
    return results


def _create_one_dimension_type(doc, source, preset, arrowheads):
    new_type = source.Duplicate(preset.name)
    _set_param(new_type, u"TEXT_FONT", preset.get(u"font") or u"Arial")
    _set_param(new_type, u"TEXT_SIZE",
               fet_core.to_number(preset.get(u"size_mm"), 2.5), True)
    gap = fet_core.to_number(preset.get(u"witness_gap_mm"), 0)
    if gap > 0:
        _set_param(new_type, u"WITNESS_LINE_GAP_TO_ELEMENT", gap, True)
    tick = arrowheads.get(fet_core._as_text(preset.get(u"tick")).lower())
    if tick is not None:
        _set_param(new_type, u"DIM_STYLE_TICK_MARK", tick)
    arrow = arrowheads.get(fet_core._as_text(preset.get(u"arrowhead")).lower())
    if arrow is not None:
        _set_param(new_type, u"DIM_LEADER_ARROWHEAD", arrow)
    return new_type


def create_dimension_types(doc, presets):
    results = []
    if not presets:
        return [Result(SKIPPED, u"dimension types", u"nothing was ticked")]
    types = fet_model.dimension_types(doc)
    if not types:
        return [Result(FAILED, u"dimension types",
                       u"this family carries no dimension type to duplicate from")]
    linear = None
    for name, element_id, style in types:
        if u"Linear" in style:
            linear = element_id
            break
    source = doc.GetElement(linear or types[0][1])
    existing = set([name.lower() for name, element_id, style in types])
    arrowheads = {}
    for name, element_id in fet_model.arrowhead_names(doc):
        arrowheads[name.lower()] = element_id
    transaction = _start(doc, u"RevoBIM - load dimension types")
    for preset in presets:
        if preset.name.lower() in existing:
            results.append(Result(EXISTING, preset.name, u"already here"))
            continue
        try:
            _isolated(_create_one_dimension_type, doc, source, preset, arrowheads)
        except Exception:
            results.append(Result(FAILED, preset.name,
                                  _last_line(traceback.format_exc())))
            continue
        existing.add(preset.name.lower())
        results.append(Result(CREATED, preset.name, preset.get(u"tick")))
    if _commit(transaction, results):
        after = set([name.lower() for name, element_id, style
                     in fet_model.dimension_types(doc)])
        for item in results:
            if item.status == CREATED and item.subject.lower() not in after:
                item.status = FAILED
                item.message = u"accepted, but the dimension type is not there"
    return results


# =========================================================================
# Standard reference plane layouts
# =========================================================================

def _view_runs_the_right_way(view, wanted):
    u"""A plan looks down Z; the height layout has to be run from a front
    or back elevation, because a left or right elevation draws those planes
    edge on to the screen and Revit will not take them."""
    try:
        direction = view.ViewDirection
    except Exception:
        return True, u""
    if wanted == u"plan":
        if abs(direction.Z) > 0.9:
            return True, u""
        return False, u"the active view does not look straight down"
    if abs(direction.Y) > 0.9:
        return True, u""
    return False, (u"run this from a front or back elevation - a left or "
                   u"right elevation draws these planes edge on")


def _make_plane(doc, view, axis, offset_mm, extent_mm, view_kind=u"plan"):
    offset = fet_core.mm_to_ft(offset_mm)
    extent = fet_core.mm_to_ft(extent_mm)
    if axis == u"x" and view_kind == u"elevation":
        # Seen in a front elevation, an X plane runs UP the screen, so the
        # line has to lie along Z and the cut vector becomes Y.  Drawing it
        # along Y instead puts the line perpendicular to the screen and
        # Revit refuses it.
        bubble = XYZ(offset, 0.0, -extent)
        free = XYZ(offset, 0.0, extent)
        cut = XYZ.BasisY
    elif axis == u"x":
        bubble = XYZ(offset, -extent, 0.0)
        free = XYZ(offset, extent, 0.0)
        cut = XYZ.BasisZ
    elif axis == u"y":
        bubble = XYZ(-extent, offset, 0.0)
        free = XYZ(extent, offset, 0.0)
        cut = XYZ.BasisZ
    else:
        # A Top / Bottom plane is horizontal: its normal is Z, so the
        # plane spans X and Y and the cut vector has to be Y.
        bubble = XYZ(-extent, 0.0, offset)
        free = XYZ(extent, 0.0, offset)
        cut = XYZ.BasisY
    return doc.FamilyCreate.NewReferencePlane(bubble, free, cut, view)


def _name_plane(plane, wanted):
    u"""Renaming is not reliable through one route and neither route
    reliably raises, so it is tried both ways and read back."""
    try:
        plane.Name = wanted
    except Exception:
        pass
    try:
        if plane.Name == wanted:
            return True
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        Element.Name.SetValue(plane, wanted)
    except Exception:
        pass
    try:
        return plane.Name == wanted
    except Exception:
        return False


def _set_is_reference(plane, value):
    u"""ELEM_REFERENCE_PLANE_IS_REFERENCE is an integer parameter, not an
    enum the API hands you."""
    member = fet_model.bip(u"ELEM_REFERENCE_PLANE_IS_REFERENCE")
    if member is None:
        return False
    try:
        parameter = plane.get_Parameter(member)
        if parameter is None or parameter.IsReadOnly:
            return False
        return bool(parameter.Set(int(value)))
    except Exception:
        return False


def _dimension_line(axis, fixed_mm, low_mm, high_mm, view_kind=u"plan"):
    low = fet_core.mm_to_ft(low_mm)
    high = fet_core.mm_to_ft(high_mm)
    fixed = fet_core.mm_to_ft(fixed_mm)
    if axis == u"x" and view_kind == u"elevation":
        return Line.CreateBound(XYZ(low, 0.0, fixed), XYZ(high, 0.0, fixed))
    if axis == u"x":
        return Line.CreateBound(XYZ(low, fixed, 0.0), XYZ(high, fixed, 0.0))
    if axis == u"y":
        return Line.CreateBound(XYZ(fixed, low, 0.0), XYZ(fixed, high, 0.0))
    return Line.CreateBound(XYZ(fixed, 0.0, low), XYZ(fixed, 0.0, high))


def _family_parameter(doc, name, group_option, is_instance):
    manager = doc.FamilyManager
    try:
        found = manager.get_Parameter(name)
        if found is not None:
            return found, False
    except Exception:
        pass
    spec = None
    try:
        from Autodesk.Revit.DB import SpecTypeId
        spec = SpecTypeId.Length
    except Exception:
        spec = None
    if spec is None:
        try:
            from Autodesk.Revit.DB import ParameterType
            spec = ParameterType.Length
        except Exception:
            spec = None
    if spec is None:
        raise Exception(u"this release offers neither SpecTypeId nor ParameterType")
    group_value = group_option.value if group_option is not None else None
    return manager.AddParameter(name, group_value, spec, is_instance), True


def apply_plane_layout(doc, view, layout_key, settings):
    u"""Create the layout's reference planes, equalise them about the
    centre, and label the driving dimensions with family parameters."""
    results = []
    layout = fet_planes.get_layout(layout_key)
    wanted_view = layout[u"view"]

    if not fet_model.is_family(doc):
        return [Result(FAILED, u"the document", u"this is not a family document")]

    ok, why = fet_model.view_is_suitable(view, wanted_view)
    if not ok:
        return [Result(SKIPPED, layout[u"name"], why)]
    ok, why = _view_runs_the_right_way(view, wanted_view)
    if not ok:
        return [Result(SKIPPED, layout[u"name"], why)]

    sizes = {
        u"w": fet_core.setting_mm(settings, u"width_mm"),
        u"d": fet_core.setting_mm(settings, u"depth_mm"),
        u"h": fet_core.setting_mm(settings, u"height_mm"),
        u"c": fet_core.setting_mm(settings, u"clearance_mm"),
        u"r": fet_core.setting_mm(settings, u"radius_mm"),
    }
    extent = fet_core.setting_mm(settings, u"plane_extent_mm")
    dim_offset = fet_core.setting_mm(settings, u"dim_offset_mm")
    dim_step = fet_core.setting_mm(settings, u"dim_step_mm")
    label_dims = fet_core.setting_on(settings, u"label_plane_dims")
    make_params = fet_core.setting_on(settings, u"create_plane_params")
    binding = fet_core._as_text(settings.get(u"plane_params_binding", u"type"))
    is_instance = binding == u"instance"
    group_option = fet_model.default_group_option(
        fet_core._as_text(settings.get(u"default_group", u"Data")))

    # Which family parameter this PAGE drives, falling back to the house
    # default name where the page has not been pointed at one.
    mapping = fet_core.parse_layout_params(settings.get(u"layout_params", u""))
    param_names = {}
    for key in fet_core.PLANE_PARAM_KEYS:
        param_names[key] = fet_core.layout_param_name(
            mapping, layout_key, key, settings)

    existing_planes = fet_model.reference_planes(doc)
    made = {}

    transaction = _start(doc, u"RevoBIM - standard planes")

    for name, axis, offset, ref_type in fet_planes.plane_positions(layout_key, sizes):
        if name in existing_planes:
            made[name] = existing_planes[name]
            results.append(Result(EXISTING, name,
                                  u"a reference plane of that name is already "
                                  u"here and was left where it is"))
            continue
        try:
            plane = _isolated(_make_plane, doc, view, axis, offset, extent,
                              wanted_view)
        except Exception:
            results.append(Result(FAILED, name, _last_line(traceback.format_exc())))
            continue
        named = _name_plane(plane, name)
        _set_is_reference(plane, ref_type)
        made[name] = plane
        detail = u"{0} at {1:.0f}mm, {2}".format(
            axis.upper(), offset, fet_planes.REF_NAMES.get(ref_type, u""))
        if not named:
            detail += u" (Revit would not take the name)"
        results.append(Result(CREATED, name, detail))

    # ----- the dimensions --------------------------------------------
    for kind, axis, pairs, param_key, slot in fet_planes.dimension_specs(
            layout_key, sizes):
        planes = [made.get(name) for name, offset in pairs]
        if None in planes:
            results.append(Result(SKIPPED,
                                  u"the {0} dimension".format(
                                      u"EQ" if kind == u"eq" else param_key or u""),
                                  u"a plane it needs is not there"))
            continue
        array = ReferenceArray()
        bad = False
        for plane in planes:
            try:
                array.Append(plane.GetReference())
            except Exception:
                bad = True
                break
        if bad or array.Size < 2:
            results.append(Result(FAILED, u"a dimension",
                                  u"Revit would not give up a reference for "
                                  u"one of the planes"))
            continue

        low = pairs[0][1]
        high = pairs[-1][1]
        # The dimension line sits clear of the planes it is not measuring,
        # stepped out by its slot so two runs on the same axis do not land
        # on top of each other.
        across = u"y" if axis == u"x" else u"x"
        others = [offset for name, offset in _offsets_on(layout_key, sizes, across)]
        base = min(others) if others else 0.0
        fixed = base - dim_offset - dim_step * slot

        try:
            line = _dimension_line(axis, fixed, low, high, wanted_view)
            dimension = _isolated(_new_dimension, doc, view, line, array)
        except Exception:
            results.append(Result(FAILED, u"a dimension",
                                  _last_line(traceback.format_exc())))
            continue

        if kind == u"eq":
            worked = False
            try:
                dimension.AreSegmentsEqual = True
                worked = True
            except Exception:
                worked = False
            results.append(Result(CREATED if worked else FAILED,
                                  u"EQ across {0}".format(
                                      u" / ".join([n for n, o in pairs])),
                                  u"" if worked else
                                  u"the dimension was placed but Revit would "
                                  u"not set it equal"))
            continue

        name = param_names.get(param_key, param_key or u"")
        assigned = fet_core.assigned_param(mapping, layout_key, param_key)
        if not name or not fet_core.should_label(assigned, label_dims,
                                                 make_params):
            results.append(Result(CREATED,
                                  u"the {0} dimension".format(name or axis),
                                  u"placed, not labelled"))
            continue
        try:
            parameter, is_new = _isolated(_family_parameter, doc, name,
                                          group_option, is_instance)
            dimension.FamilyLabel = parameter
        except Exception:
            results.append(Result(FAILED, u"the {0} label".format(name),
                                  _last_line(traceback.format_exc())))
            continue
        if is_new and assigned:
            note = (u"the parameter this page was pointed at was not in the "
                    u"family, so it was created and labelled")
        elif is_new:
            note = u"created as a {0} parameter, driving the dimension".format(
                u"instance" if is_instance else u"type")
        else:
            note = (u"the family's own parameter, now driving the dimension - "
                    u"its value is the measured distance")
        results.append(Result(CREATED, name, note))

    _commit(transaction, results)
    return results


def _offsets_on(layout_key, sizes, axis):
    out = []
    for name, plane_axis, offset, ref in fet_planes.plane_positions(layout_key, sizes):
        if plane_axis == axis:
            out.append((name, offset))
    return out


def _new_dimension(doc, view, line, array):
    return doc.FamilyCreate.NewDimension(view, line, array)


# =========================================================================
# The ExternalEvent
#
# A modeless window cannot start a transaction directly.  Work is queued
# and the event raised; NOTHING waits for it, because Revit raises the
# event on the same thread the window lives on and blocking that thread to
# wait is a deadlock.
# =========================================================================

class OpsHandler(IExternalEventHandler):
    def __init__(self):
        self.jobs = []

    def queue(self, function, done=None):
        self.jobs.append((function, done))

    def Execute(self, uiapp):
        while self.jobs:
            function, done = self.jobs.pop(0)
            results = None
            error = None
            try:
                results = function(uiapp)
            except Exception:
                error = traceback.format_exc()
                fet_core.log(u"external event job failed\n{0}".format(error))
                results = [Result(FAILED, u"the job", _last_line(error))]
            if done is not None:
                try:
                    done(results)
                except Exception:
                    fet_core.log(u"the completion callback failed\n{0}".format(
                        traceback.format_exc()))

    def GetName(self):
        return u"RevoBIM Family Editor Tools"


# Parked at module level, with a version stamped key, or the persistent
# engine collects them out from under the user.
HANDLER = None
EVENT = None


def external_event():
    global HANDLER, EVENT
    if HANDLER is None:
        HANDLER = OpsHandler()
    if EVENT is None:
        EVENT = ExternalEvent.Create(HANDLER)
    return HANDLER, EVENT


# =========================================================================
# Loading out of another open model
#
# Materials and annotation types are COPIED, so their appearance assets,
# patterns and arrowheads come with them.  A line style cannot be copied
# that way - a subcategory is not an element you can hand to CopyElements -
# so it is rebuilt from what was read off it, which is why a line pattern
# the family does not carry is reported rather than invented.
# =========================================================================

class KeepTheDestination(IDuplicateTypeNamesHandler):
    def OnDuplicateTypeNamesFound(self, args):
        return DuplicateTypeAction.UseDestinationTypes


def _copy_options():
    options = CopyPasteOptions()
    try:
        options.SetDuplicateTypeNamesHandler(KeepTheDestination())
    except Exception:
        pass
    return options


def _copy_one(doc, source_doc, element_id):
    ids = List[ElementId]()
    ids.Add(element_id)
    return ElementTransformUtils.CopyElements(
        source_doc, ids, doc, Transform.Identity, _copy_options())


def load_from_model(doc, source_doc, kind, items):
    u"""items are fet_model.ScanItem read out of source_doc.

    CopyElements between two documents OPENS ITS OWN TRANSACTION, so it
    must not be called inside one.  Doing that is what answered a perfectly
    ordinary material with "Copying one or more elements failed".  The
    whole batch goes in one call, and a refused batch is replayed one at a
    time so the one at fault is named and only that one is lost.
    """
    results = []
    if not fet_model.is_family(doc):
        return [Result(FAILED, u"the document", u"this is not a family document")]
    if not items:
        return [Result(SKIPPED, kind, u"nothing was ticked")]
    if source_doc is None:
        return [Result(FAILED, kind, u"that model is no longer open")]

    already = fet_model.existing_names(doc, kind)
    if kind == u"linestyle":
        return _rebuild_line_styles(doc, items, already)

    wanted = []
    present = []
    for item in items:
        if item.name.lower() in already:
            # Already here does NOT mean nothing to do.  A material copied
            # by an earlier run can be sitting in the family with no
            # appearance asset at all, and refusing to look at it again is
            # what made that impossible to put right.
            results.append(Result(EXISTING, item.name,
                                  u"already in this family"))
            present.append(item)
        else:
            wanted.append(item)
    if not wanted and not present:
        return results

    # A group is not a transaction, so CopyElements may run inside one -
    # and Revit's undo then sees the whole load as a single step.
    group = TransactionGroup(doc, u"RevoBIM - load from another model")
    try:
        group.Start()
    except Exception:
        group = None

    refused = []
    if not wanted:
        pass
    elif len(wanted) > 1 and _copy_many(doc, source_doc, wanted):
        for item in wanted:
            results.append(Result(CREATED, item.name, item.detail))
    else:
        for item in wanted:
            if _copy_many(doc, source_doc, [item]):
                results.append(Result(CREATED, item.name, item.detail))
            else:
                refused.append(item)

    # Anything Revit would not copy is rebuilt from what was read off it,
    # which is worth saying out loud: the colour and class come across, the
    # appearance asset does not.
    for item in refused:
        rebuilt = _rebuild_one(doc, kind, item)
        if rebuilt is None:
            results.append(Result(FAILED, item.name,
                                  u"Revit refused to copy it, and it cannot "
                                  u"be rebuilt from what was read"))
        else:
            results.extend(rebuilt)

    if kind == u"material":
        landed = [item for item in wanted if item not in refused] + present
        results.extend(_ensure_appearance(doc, source_doc, landed))

    if group is not None:
        try:
            group.Assimilate()
        except Exception:
            pass

    after = fet_model.existing_names(doc, kind)
    for row in results:
        if row.status == CREATED and row.subject.lower() not in after:
            row.status = FAILED
            row.message = u"the copy was accepted but it is not here"
    return results


def _copy_many(doc, source_doc, items):
    u"""The things themselves AND what they point at.  A material handed
    over on its own can arrive with no appearance asset behind it, so its
    assets and its fill patterns go in the same call."""
    ids = List[ElementId]()
    seen = set()
    for item in items:
        for element_id in [item.element_id] + list(item.depends or []):
            if element_id is None:
                continue
            key = fet_core.eid_value(element_id)
            if key in seen:
                continue
            seen.add(key)
            ids.Add(element_id)
    if ids.Count == 0:
        return False
    try:
        ElementTransformUtils.CopyElements(source_doc, ids, doc,
                                           Transform.Identity,
                                           _copy_options())
        return True
    except Exception:
        fet_core.log(u"copy of {0} refused\n{1}".format(
            u", ".join([item.name for item in items]),
            traceback.format_exc()))
        return False


def _rename_element(element, name):
    u"""Both routes, then read it back - which one works varies with the
    IronPython version and neither reliably raises."""
    if element is None:
        return False
    try:
        element.Name = name
    except Exception:
        pass
    try:
        if element.Name == name:
            return True
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import Element
        Element.Name.SetValue(element, name)
    except Exception:
        pass
    try:
        return element.Name == name
    except Exception:
        return False


def _copy_returning_id(doc, source_doc, element_id):
    ids = List[ElementId]()
    ids.Add(element_id)
    try:
        copied = ElementTransformUtils.CopyElements(
            source_doc, ids, doc, Transform.Identity, _copy_options())
    except Exception:
        fet_core.log(u"appearance asset refused\n{0}".format(
            traceback.format_exc()))
        _trace_fail(u"CopyElements on the appearance asset element", 2)
        return None
    for new_id in copied or []:
        return new_id
    return None


def _unique_asset_name(doc, wanted):
    return fet_core.unique_name(wanted,
                                list(fet_model.appearance_assets(doc).keys()))


def _wanted_asset_name(source_doc, item):
    return u"{0} ({1})".format(item.asset_name,
                               fet_model.document_title(source_doc))


def _attach(doc, material_id, asset_id, title, results):
    transaction = _start(doc, title)
    ok = False
    try:
        doc.GetElement(material_id).AppearanceAssetId = asset_id
        ok = True
    except Exception:
        results.append(Result(SKIPPED, u"an appearance asset",
                              u"would not attach: {0}".format(
                                  _last_line(traceback.format_exc()))))
    return _commit(transaction, results) and ok


# =========================================================================
# Getting an asset element in the FAMILY that the source's properties can
# actually be written into.
#
# Three routes, because none of them can be relied on:
#
#  - copying the source AppearanceAssetElement across often does not
#    happen at all.  Revit answers by inventing a default Generic asset,
#    attaching that, and raising nothing;
#  - creating one from a library asset of the same schema needs that schema
#    to be in the library this release ships;
#  - duplicating whatever the family already attached always works, but is
#    only any use where its schema matches the source's.
#
# Whichever lands, the source's properties are then written into it, so a
# route that produced an empty asset of the right shape is still a win.
# =========================================================================

def _route_copied_element(doc, source_doc, item, results):
    assets = fet_model.appearance_assets(doc)
    clash_id = assets.get(item.asset_name.lower())
    if clash_id is not None:
        # CopyPasteOptions cannot be told "copy it anyway" - its only
        # answer to a name clash is UseDestinationTypes - so the family's
        # own asset of that name is parked for the length of the copy.
        transaction = _start(doc, u"RevoBIM - park an appearance asset")
        moved = _rename_element(doc.GetElement(clash_id),
                                u"{0}{1}".format(fet_core.PARK_PREFIX,
                                                 item.asset_name))
        _commit(transaction, results)
        if not moved:
            return None

    new_id = _copy_returning_id(doc, source_doc, item.asset_id)
    _trace(u"route 1 copy of the asset element returned {0}".format(
        fet_core.eid_value(new_id) if new_id is not None else u"nothing"), 2)

    if clash_id is not None:
        transaction = _start(doc, u"RevoBIM - put the parked asset back")
        _rename_element(doc.GetElement(clash_id), item.asset_name)
        _commit(transaction, results)
    return new_id


def _route_library_asset(doc, source_doc, item, source_asset, results):
    schema = fet_model.asset_base_schema(source_asset)
    try:
        app = doc.Application
    except Exception:
        return None
    library = fet_model.library_assets(app, schema)
    _trace(u"route 2 found {0} library assets for schema '{1}'".format(
        len(library), schema), 2)
    if not library:
        return None
    try:
        from Autodesk.Revit.DB import AppearanceAssetElement
    except Exception:
        return None
    transaction = _start(doc, u"RevoBIM - create an appearance asset")
    new_id = None
    try:
        name = _unique_asset_name(doc, _wanted_asset_name(source_doc, item))
        new_id = AppearanceAssetElement.Create(doc, name, library[0]).Id
    except Exception:
        fet_core.log(u"AppearanceAssetElement.Create refused\n{0}".format(
            traceback.format_exc()))
        _trace_fail(u"AppearanceAssetElement.Create", 2)
        new_id = None
    if new_id is None:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return None
    _commit(transaction, results)
    return new_id


def _route_family_asset_of_schema(doc, source_doc, item, source_asset,
                                  results):
    u"""Duplicate an appearance asset element already in the family that is
    built on the same schema.  This is the route that works when nothing
    will cross from the other document and the material has no asset of its
    own to duplicate."""
    schema = fet_model.asset_base_schema(source_asset)
    source_id = fet_model.family_asset_of_schema(doc, schema)
    _trace(u"route 3 {0} a '{1}' asset already in the family".format(
        u"found" if source_id is not None else u"found no", schema), 2)
    if source_id is None:
        return None
    return _duplicate_asset(doc, source_doc, item, source_id, results)


def _duplicate_asset(doc, source_doc, item, source_id, results):
    transaction = _start(doc, u"RevoBIM - duplicate an appearance asset")
    new_id = None
    try:
        name = _unique_asset_name(doc, _wanted_asset_name(source_doc, item))
        new_id = doc.GetElement(source_id).Duplicate(name).Id
    except Exception:
        _trace_fail(u"duplicating an appearance asset", 2)
        new_id = None
    if new_id is None:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return None
    _commit(transaction, results)
    return new_id


def _route_duplicate_existing(doc, source_doc, item, material_id, results):
    u"""Duplicated rather than edited in place, because Revit may have
    handed the same default asset to several materials and editing it would
    change all of them."""
    material = doc.GetElement(material_id)
    found_name, found_id = fet_model.appearance_asset(doc, material)
    _trace(u"route 4 {0} an asset on the material itself".format(
        u"found" if found_id is not None else u"found no"), 2)
    if found_id is None:
        return None
    return _duplicate_asset(doc, source_doc, item, found_id, results)


# =========================================================================
# Writing one asset's properties into another
# =========================================================================

def _copy_property(source, target):
    u"""Every route to a value, tried in turn.  A colour is four doubles, a
    glossiness is one, a highlight is an enum - and a read only property
    throws rather than saying so."""
    try:
        values = source.GetValueAsDoubles()
        target.SetValueAsDoubles(values)
        return True
    except Exception:
        pass
    for getter, setter in ((u"GetValueAsInts", u"SetValueAsInts"),
                           (u"GetValueAsBools", u"SetValueAsBools"),
                           (u"GetValueAsStrings", u"SetValueAsStrings")):
        try:
            target_set = getattr(target, setter)
            target_set(getattr(source, getter)())
            return True
        except Exception:
            continue
    try:
        target.Value = source.Value
        return True
    except Exception:
        return False


def _connected(prop):
    try:
        if prop.NumberOfConnectedProperties <= 0:
            return None
        return prop.GetSingleConnectedAsset()
    except Exception:
        return None


def write_asset(source_asset, target_asset, depth=0):
    u"""Returns how many properties were written.  Zero means the two
    assets have no property names in common - a different schema - and
    nothing could be carried across."""
    written = 0
    if source_asset is None or target_asset is None:
        return 0
    for source_property in fet_model.asset_properties(source_asset):
        try:
            name = source_property.Name
        except Exception:
            continue
        if fet_model.is_volatile(name):
            continue
        target = None
        try:
            target = target_asset.FindByName(name)
        except Exception:
            target = None
        if target is None:
            continue
        if _copy_property(source_property, target):
            written += 1
        # A texture hangs off its property as a connected asset, so the
        # bitmap is only carried if that is walked too.
        if depth >= fet_model.FINGERPRINT_DEPTH:
            continue
        source_connected = _connected(source_property)
        if source_connected is None:
            continue
        target_connected = _connected(target)
        if target_connected is None:
            try:
                target.AddConnectedAsset(source_connected.Name)
                target_connected = _connected(target)
            except Exception:
                target_connected = None
        written += write_asset(source_connected, target_connected, depth + 1)
    return written


def _write_into(doc, asset_id, source_asset):
    u"""An AppearanceAssetEditScope opens its own transaction, so nothing
    may be open here."""
    try:
        from Autodesk.Revit.DB.Visual import AppearanceAssetEditScope
    except Exception:
        return 0
    try:
        scope = AppearanceAssetEditScope(doc)
        editable = scope.Start(asset_id)
        _trace(u"edit scope opened on asset {0}, schema '{1}'".format(
            fet_core.eid_value(asset_id), fet_model.asset_schema(editable)), 2)
        written = write_asset(source_asset, editable)
        scope.Commit(True)
        return written
    except Exception:
        fet_core.log(u"writing the appearance properties failed\n{0}".format(
            traceback.format_exc()))
        _trace_fail(u"the appearance asset edit scope", 2)
        return 0


# =========================================================================
# The whole job, per material
# =========================================================================

def _ensure_appearance(doc, source_doc, items):
    u"""Every material that arrived is asked whether the asset behind it is
    really the one it came with - not just whether it has one.  Revit will
    happily invent a default Generic asset and attach that, which passes a
    'has an asset' check and renders grey."""
    results = []
    wanted = [item for item in items
              if item.asset_name and item.asset_id is not None]
    if not wanted:
        return results

    here = {}
    for name, element_id in fet_model.materials(doc):
        here[name.lower()] = element_id

    _trace(u"checking the appearance of {0} material(s)".format(len(wanted)), 0)
    for item in wanted:
        _trace(u"{0}".format(item.name), 0)
        material_id = here.get(item.name.lower())
        if material_id is None:
            _trace(u"it is not in the family, so there is nothing to fix", 1)
            continue
        source_print = fet_model.element_fingerprint(source_doc, item.asset_id)
        source_asset = fet_model.rendering_asset_by_id(source_doc,
                                                       item.asset_id)
        if source_asset is None:
            results.append(Result(SKIPPED, item.name,
                                  u"this release would not read its "
                                  u"appearance asset"))
            continue
        if source_print and _appearance_matches(doc, material_id, source_print):
            _trace(u"its appearance already matches the source", 1)
            continue
        _trace(u"its appearance does not match the source - bringing it "
               u"across", 1)
        results.extend(_bring_the_look(doc, source_doc, item, material_id,
                                       source_asset, source_print))
    return results


def _bring_the_look(doc, source_doc, item, material_id, source_asset,
                    source_print):
    results = []
    routes = (
        (u"copied whole",
         lambda: _route_copied_element(doc, source_doc, item, results)),
        (u"built from Revit's own {0} asset".format(
            fet_model.asset_base_schema(source_asset) or u"library"),
         lambda: _route_library_asset(doc, source_doc, item, source_asset,
                                      results)),
        (u"built on a {0} asset already in the family".format(
            fet_model.asset_base_schema(source_asset) or u"matching"),
         lambda: _route_family_asset_of_schema(doc, source_doc, item,
                                               source_asset, results)),
        (u"written into the one the family made",
         lambda: _route_duplicate_existing(doc, source_doc, item, material_id,
                                           results)),
    )

    for label, route in routes:
        _trace(u"trying: {0}".format(label))
        try:
            asset_id = route()
        except Exception:
            fet_core.log(u"route '{0}' failed for {1}\n{2}".format(
                label, item.name, traceback.format_exc()))
            _trace_fail(u"the route itself", 2)
            asset_id = None
        if asset_id is None:
            _trace(u"no asset element from this route", 2)
            continue
        if not _attach(doc, material_id, asset_id,
                       u"RevoBIM - attach the appearance asset", results):
            _trace(u"the asset would not attach to the material", 2)
            continue
        # Whichever route produced it, the source's own properties are
        # written in - a route that produced an empty asset of the right
        # shape is still a win.
        written = _write_into(doc, asset_id, source_asset)
        _trace(u"{0} properties written across".format(written), 2)
        transaction = _start(doc, u"RevoBIM - name the appearance asset")
        _rename_element(doc.GetElement(asset_id),
                        _unique_asset_name(doc,
                                           _wanted_asset_name(source_doc, item)))
        _commit(transaction, results)

        if source_print and _appearance_matches(doc, material_id, source_print):
            _trace(u"it reads back identical to the source", 2)
            results.append(Result(EXISTING, item.name,
                                  u"appearance asset {0}".format(label)))
            return results
        _trace(u"it does not read back identical to the source", 2)
        if written:
            results.append(Result(EXISTING, item.name,
                                  u"appearance asset {0} - {1} properties "
                                  u"written, but it does not read back "
                                  u"identical".format(label, written)))
            return results

    results.append(Result(SKIPPED, item.name,
                          u"its appearance asset '{0}' could not be brought "
                          u"across - the material is here but the look is "
                          u"not".format(item.asset_name)))
    return results


def _appearance_matches(doc, material_id, source_print):
    material = doc.GetElement(material_id)
    if material is None:
        return False
    found_name, found_id = fet_model.appearance_asset(doc, material)
    if found_id is None:
        return False
    return fet_model.same_asset(
        fet_model.element_fingerprint(doc, found_id), source_print)


def _rebuild_one(doc, kind, item):
    u"""The fallback when a copy is refused."""
    if kind != u"material":
        return None
    values = {u"name": item.name}
    values.update(item.extra or {})
    results = create_materials(doc, [fet_core.Preset(u"material", values)])
    for row in results:
        if row.status == CREATED:
            row.message = u"rebuilt from its colour and class - Revit would " \
                          u"not copy it, so its appearance asset did not come"
    return results


def _rebuild_line_styles(doc, items, already):
    presets = []
    for item in items:
        values = {u"name": item.name}
        values.update(item.extra)
        presets.append(fet_core.Preset(u"linestyle", values))
    return create_line_styles(doc, presets)


# =========================================================================
# Opening the view a layout has to be set out in
# =========================================================================

def activate_layout_view(uiapp, doc, layout_key):
    u"""Returns (view, note).  Changing the active view is a UI call and
    cannot happen inside a transaction, so it is done before one starts."""
    wanted = fet_planes.get_layout(layout_key)[u"view"]
    uidoc = uiapp.ActiveUIDocument
    current = None
    try:
        current = uidoc.ActiveView
    except Exception:
        current = None
    if fet_model.view_kind(current) == wanted and \
            fet_model.view_points_the_right_way(current, wanted):
        return current, None

    view = fet_model.find_layout_view(doc, wanted,
                                      fet_planes.view_names_for(layout_key))
    if view is None:
        return current, Result(
            SKIPPED, u"the view",
            u"this family has no {0} view to set out in".format(wanted))
    try:
        uidoc.ActiveView = view
    except Exception:
        return current, Result(
            SKIPPED, u"the view",
            u"Revit would not open '{0}' - open it and run this "
            u"again".format(_view_name(view)))
    return view, Result(EXISTING, u"the view",
                        u"opened '{0}' to set out in".format(_view_name(view)))


def view_name(view):
    try:
        return view.Name
    except Exception:
        return u"?"


_view_name = view_name


# =========================================================================
# Swaps and edits, applied together
# =========================================================================

def apply_parameter_changes(doc, app, spf_path, swap_rows, edits):
    u"""The swaps first, then the edits, because an edit may be waiting on
    a parameter a swap is about to bring in.  Two transactions, so a
    refused edit does not cost the swaps."""
    results = []
    if swap_rows:
        results.extend(add_shared_parameters(doc, app, spf_path, swap_rows,
                                             {}))
    if edits:
        results.extend(apply_parameter_edits(doc, edits))
    if not results:
        results.append(Result(SKIPPED, u"the table",
                              u"nothing is waiting to be applied"))
    return results


# =========================================================================
# The diagnostic run
# =========================================================================

def diagnose_materials(doc, source_doc, items):
    u"""Load the ticked materials with everything on the appearance path
    reporting what it did, and dump both documents' view of each material
    before and after.  Returns (trace, results)."""
    global TRACE
    trace = fet_core.Trace(
        u"RevoBIM Family Editor Tools - material transfer diagnostics")
    TRACE = trace
    results = []
    try:
        trace.heading(u"Environment")
        try:
            fet_model.describe_environment(doc, source_doc, trace)
        except Exception:
            trace.fail(u"reading the environment", traceback.format_exc())

        for item in items:
            trace.heading(u"SOURCE material: {0}".format(item.name))
            try:
                fet_model.describe_material(source_doc,
                                            source_doc.GetElement(item.element_id),
                                            trace)
            except Exception:
                trace.fail(u"reading the source material",
                           traceback.format_exc())
            trace.note(u"dependencies handed to CopyElements: {0}".format(
                [fet_core.eid_value(e) for e in item.depends or []]), 1)
            trace.note(u"appearance asset element name: {0}".format(
                item.asset_name or u"<none>"), 1)

        trace.heading(u"The load")
        try:
            results = load_from_model(doc, source_doc, u"material", items)
        except Exception:
            trace.fail(u"the load itself", traceback.format_exc())
        for row in results:
            trace.note(u"{0}: {1} - {2}".format(row.status, row.subject,
                                                row.message), 1)

        here = {}
        for name, element_id in fet_model.materials(doc):
            here[name.lower()] = element_id
        for item in items:
            trace.heading(u"FAMILY material after the load: {0}".format(
                item.name))
            element_id = here.get(item.name.lower())
            try:
                fet_model.describe_material(
                    doc, doc.GetElement(element_id) if element_id else None,
                    trace)
            except Exception:
                trace.fail(u"reading the material back",
                           traceback.format_exc())
    finally:
        TRACE = None
    return trace, results


# =========================================================================
# The family icon - the thumbnail view
# =========================================================================

# The General Settings tick, and the categories it hides.  A member that
# does not exist on a release is skipped rather than throwing, which is why
# they are named rather than imported.
HIDE_CATEGORIES = {
    u"icon_hide_dimensions": (u"OST_Dimensions",),
    u"icon_hide_reference_points": (u"OST_ReferencePoints",),
    u"icon_hide_reference_lines": (u"OST_ReferenceLines",),
    u"icon_hide_reference_planes": (u"OST_CLines",),
    u"icon_hide_text_notes": (u"OST_TextNotes",),
    u"icon_hide_invisible_lines": (u"OST_InvisibleLines",),
    u"icon_hide_room_points": (u"OST_RoomCalculationPoint",),
    u"icon_hide_connectors": (u"OST_ConnectorElem", u"OST_DuctConnectors",
                              u"OST_PipeConnectors",
                              u"OST_ElectricalInternalCircuits"),
    u"icon_hide_host": (u"OST_Walls", u"OST_Floors", u"OST_Roofs",
                        u"OST_Ceilings"),
    u"icon_hide_imported": (u"OST_ImportObjectStyles",),
}


def _three_d_type(doc):
    from Autodesk.Revit.DB import ViewFamily, ViewFamilyType
    for item in FilteredElementCollector(doc).OfClass(ViewFamilyType):
        try:
            if item.ViewFamily == ViewFamily.ThreeDimensional:
                return item
        except Exception:
            continue
    return None


def _existing_view(doc, name):
    from Autodesk.Revit.DB import View3D
    for item in FilteredElementCollector(doc).OfClass(View3D):
        try:
            if item.IsTemplate:
                continue
            if item.Name == name:
                return item
        except Exception:
            continue
    return None


def _set_display_style(view, key, results):
    from Autodesk.Revit.DB import DisplayStyle
    member = getattr(DisplayStyle, fet_core._as_text(key), None)
    if member is None:
        results.append(Result(SKIPPED, u"the display style",
                              u"'{0}' is not a display style on this "
                              u"release".format(key)))
        return
    try:
        view.DisplayStyle = member
    except Exception:
        results.append(Result(SKIPPED, u"the display style",
                              _last_line(traceback.format_exc())))


def _set_detail_level(view, key, results):
    from Autodesk.Revit.DB import ViewDetailLevel
    member = getattr(ViewDetailLevel, fet_core._as_text(key), None)
    if member is None:
        return
    try:
        view.DetailLevel = member
    except Exception:
        pass


def _hide_categories(doc, view, settings, results):
    for key, names in HIDE_CATEGORIES.items():
        if not fet_core.setting_on(settings, key):
            continue
        for name in names:
            member = fet_model.bic(name)
            if member is None:
                continue
            try:
                category = doc.Settings.Categories.get_Item(member)
            except Exception:
                category = None
            if category is None:
                continue
            try:
                if view.CanCategoryBeHidden(category.Id):
                    view.SetCategoryHidden(category.Id, True)
            except Exception:
                continue


def _hide_elements(doc, view, settings, results):
    u"""The things that are not a category: a void is a form with
    IsSolid false, an import is an ImportInstance."""
    from Autodesk.Revit.DB import ElementId, GenericForm, ImportInstance
    wanted = List[ElementId]()
    if fet_core.setting_on(settings, u"icon_hide_voids"):
        for item in FilteredElementCollector(doc).OfClass(GenericForm):
            try:
                if not item.IsSolid:
                    wanted.Add(item.Id)
            except Exception:
                continue
    if fet_core.setting_on(settings, u"icon_hide_imported"):
        for item in FilteredElementCollector(doc).OfClass(ImportInstance):
            try:
                wanted.Add(item.Id)
            except Exception:
                continue
    if wanted.Count == 0:
        return
    try:
        view.HideElements(wanted)
    except Exception:
        results.append(Result(SKIPPED, u"hiding voids and imports",
                              _last_line(traceback.format_exc())))


def _set_background(view, settings, results):
    if not fet_core.setting_on(settings, u"icon_gradient"):
        return
    try:
        from Autodesk.Revit.DB import Color as DbColour, ViewDisplayBackground
        background = ViewDisplayBackground.CreateGradientBackground(
            DbColour(120, 160, 200), DbColour(200, 220, 235),
            DbColour(235, 235, 235))
        view.SetBackground(background)
    except Exception:
        results.append(Result(SKIPPED, u"the gradient background",
                              u"this release would not set it"))


def build_thumbnail_view(doc, settings):
    u"""Create (or re-make) the thumbnail view and return (view, results).

    The view is rebuilt from scratch each time rather than adjusted: a view
    somebody has since tilted or filtered would otherwise produce a
    thumbnail nobody can explain.
    """
    results = []
    if not fet_model.is_family(doc):
        return None, [Result(FAILED, u"the document",
                             u"this is not a family document")]
    name = fet_core._as_text(settings.get(u"icon_view_name",
                                          u"Thumbnail View")).strip()
    if not name:
        name = u"Thumbnail View"

    view_type = _three_d_type(doc)
    if view_type is None:
        return None, [Result(FAILED, u"the view",
                             u"this family has no 3D view type to create "
                             u"from")]

    transaction = _start(doc, u"RevoBIM - build the thumbnail view")
    view = None
    try:
        from Autodesk.Revit.DB import View3D, ViewOrientation3D, XYZ as _XYZ
        existing = _existing_view(doc, name)
        if existing is not None:
            try:
                doc.Delete(existing.Id)
            except Exception:
                results.append(Result(SKIPPED, name,
                                      u"the old view would not be removed, "
                                      u"so it was left alone"))
        view = View3D.CreateIsometric(doc, view_type.Id)
        _rename_element(view, name)

        corner, up, forward = fet_core.orientation_for(
            fet_core._as_text(settings.get(u"icon_view_type",
                                           u"top_back_left")))
        try:
            view.SetOrientation(ViewOrientation3D(
                _XYZ(corner[0], corner[1], corner[2]),
                _XYZ(up[0], up[1], up[2]),
                _XYZ(forward[0], forward[1], forward[2])))
        except Exception:
            results.append(Result(SKIPPED, u"the view direction",
                                  _last_line(traceback.format_exc())))

        _set_display_style(view, settings.get(u"icon_3d_style", u"Realistic"),
                           results)
        _set_detail_level(view, settings.get(u"icon_3d_detail", u"Fine"),
                          results)
        scale = int(fet_core.to_number(settings.get(u"icon_3d_scale", u"1"), 1))
        try:
            view.Scale = max(1, scale)
        except Exception:
            pass

        _hide_categories(doc, view, settings, results)
        _hide_elements(doc, view, settings, results)
        _set_background(view, settings, results)

        if fet_core.setting_on(settings, u"icon_lock_orientation"):
            try:
                view.SaveOrientationAndLock()
            except Exception:
                results.append(Result(SKIPPED, u"locking the orientation",
                                      _last_line(traceback.format_exc())))
    except Exception:
        results.append(Result(FAILED, u"the thumbnail view",
                              _last_line(traceback.format_exc())))
        try:
            transaction.RollBack()
        except Exception:
            pass
        return None, results

    if not _commit(transaction, results):
        return None, results
    results.append(Result(CREATED, name,
                          u"3D view built and set as the preview to save"))
    return view, results


def show_view(uiapp, view):
    u"""Changing the active view is a UI call, so it happens outside any
    transaction."""
    try:
        uiapp.ActiveUIDocument.ActiveView = view
        return True
    except Exception:
        return False


def export_view_image(doc, view, folder, name, results):
    try:
        from Autodesk.Revit.DB import (ExportRange, ImageExportOptions,
                                       ImageFileType, ImageResolution,
                                       ZoomFitType)
    except Exception:
        results.append(Result(SKIPPED, u"the image export",
                              u"this release does not offer it"))
        return
    try:
        options = ImageExportOptions()
        options.ExportRange = ExportRange.SetOfViews
        ids = List[ElementId]()
        ids.Add(view.Id)
        options.SetViewsAndSheets(ids)
        options.HLRandWFViewsFileType = ImageFileType.PNG
        options.ShadowViewsFileType = ImageFileType.PNG
        options.ImageResolution = ImageResolution.DPI_150
        try:
            options.ZoomType = ZoomFitType.FitToPage
        except Exception:
            pass
        options.FilePath = os.path.join(folder, name + u".png")
        doc.ExportImage(options)
        results.append(Result(CREATED, name + u".png", u"image exported"))
    except Exception:
        results.append(Result(SKIPPED, u"the image export",
                              _last_line(traceback.format_exc())))


def save_family(doc, path, view, settings):
    u"""SaveAs with the thumbnail view as the preview, which is the only
    API route to the picture Windows and Revit's own load dialog show."""
    results = []
    try:
        from Autodesk.Revit.DB import SaveAsOptions
    except Exception:
        return [Result(FAILED, u"saving", u"SaveAsOptions is not available")]
    options = SaveAsOptions()
    try:
        options.OverwriteExistingFile = True
    except Exception:
        pass
    if view is not None:
        try:
            options.PreviewViewId = view.Id
        except Exception:
            results.append(Result(SKIPPED, u"the preview",
                                  u"this release would not take a preview "
                                  u"view, so Revit will choose one"))
    try:
        doc.SaveAs(path, options)
    except Exception:
        results.append(Result(FAILED, os.path.basename(path),
                              _last_line(traceback.format_exc())))
        return results
    results.append(Result(CREATED, os.path.basename(path),
                          u"saved with the thumbnail view as its preview"))
    if fet_core.setting_on(settings, u"icon_export_images") and view is not None:
        export_view_image(doc, view, os.path.dirname(path),
                          os.path.splitext(os.path.basename(path))[0], results)
    return results


# =========================================================================
# The flex test
#
# Every value is set, the family is regenerated, and the result is read
# back.  The whole run sits inside a TransactionGroup that is ROLLED BACK
# at the end, so a family is never left on a test value - which matters
# more than any of the reporting, because the one thing worse than a tool
# that finds no faults is one that leaves the family broken.
# =========================================================================

class WarningCatcher(IFailuresPreprocessor):
    u"""Records the warnings instead of just deleting them: a value that
    regenerates with 'constraints are not satisfied' is exactly what a
    flex run is looking for."""

    def __init__(self):
        self.messages = []

    def PreprocessFailures(self, accessor):
        try:
            for failure in accessor.GetFailureMessages():
                try:
                    self.messages.append(u"{0}".format(
                        failure.GetDescriptionText()))
                except Exception:
                    continue
            accessor.DeleteAllWarnings()
        except Exception:
            pass
        return FailureProcessingResult.Continue


class FlexRow(object):
    def __init__(self, type_name, parameter, value, status, message=u""):
        self.type_name = type_name
        self.parameter = parameter
        self.value = value
        self.status = status
        self.message = message

    def __repr__(self):
        return u"<{0} {1}={2}>".format(self.status, self.parameter, self.value)


def _flex_once(doc, manager, param, value, catcher):
    u"""Set one value, regenerate, read it back.  Returns (status,
    message)."""
    transaction = Transaction(doc, u"RevoBIM - flex")
    transaction.Start()
    try:
        options = transaction.GetFailureHandlingOptions()
        options.SetFailuresPreprocessor(catcher)
        options.SetClearAfterRollback(True)
        transaction.SetFailureHandlingOptions(options)
    except Exception:
        pass
    before = len(catcher.messages)
    try:
        manager.Set(param, value)
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return fet_core.FLEX_REFUSED, _last_line(traceback.format_exc())
    try:
        doc.Regenerate()
    except Exception:
        detail = _last_line(traceback.format_exc())
        try:
            transaction.RollBack()
        except Exception:
            pass
        return fet_core.FLEX_BROKE, detail
    try:
        status = transaction.Commit()
    except Exception:
        try:
            transaction.RollBack()
        except Exception:
            pass
        return fet_core.FLEX_BROKE, _last_line(traceback.format_exc())
    if status != TransactionStatus.Committed:
        return fet_core.FLEX_BROKE, u"the change ended as {0}".format(status)

    landed = fet_model.numeric_value(manager.CurrentType, param)
    if landed is None or abs(landed - value) > max(abs(value) * 1e-6, 1e-9):
        return fet_core.FLEX_NOT_TAKEN, u"it reads back as {0}".format(
            u"nothing" if landed is None else u"{0:g}".format(landed))
    if len(catcher.messages) > before:
        return fet_core.FLEX_WARNED, catcher.messages[-1]
    return fet_core.FLEX_OK, u""


def run_flex(doc, specs, settings):
    u"""specs are (parameter name, minimum, maximum).  Returns
    (rows, results)."""
    rows = []
    results = []
    if not fet_model.is_family(doc):
        return rows, [Result(FAILED, u"the document",
                             u"this is not a family document")]
    if not specs:
        return rows, [Result(SKIPPED, u"the flex test",
                             u"nothing was ticked")]

    manager = doc.FamilyManager
    steps = fet_core.to_number(settings.get(u"flex_steps", u"3"), 3)
    every_type = fet_core._as_text(settings.get(u"flex_types",
                                                u"all")) == u"all"
    types = fet_model.family_types(doc)
    if not types:
        return rows, [Result(FAILED, u"the flex test",
                             u"this family has no types to drive")]
    if not every_type:
        types = types[:1]

    count = fet_core.flex_test_count(len(types), specs, steps)
    if fet_core.flex_is_too_big(count):
        return rows, [Result(SKIPPED, u"the flex test",
                             u"that would be {0} rounds - narrow it down to "
                             u"{1} or fewer".format(
                                 count, fet_core.MAX_FLEX_TESTS))]

    started = None
    try:
        started = manager.CurrentType
    except Exception:
        started = None

    catcher = WarningCatcher()
    # Everything below is undone at the end.  A group rolls back every
    # transaction committed inside it, which is the only way to be sure
    # nothing is left on a test value.
    group = TransactionGroup(doc, u"RevoBIM - flex test")
    try:
        group.Start()
    except Exception:
        return rows, [Result(FAILED, u"the flex test",
                             u"Revit would not open a transaction group, so "
                             u"the run was not started - it could not have "
                             u"been undone afterwards")]

    try:
        for type_name, family_type in types:
            try:
                transaction = _start(doc, u"RevoBIM - flex type")
                manager.CurrentType = family_type
                _commit(transaction, results)
            except Exception:
                rows.append(FlexRow(type_name, u"", u"",
                                    fet_core.FLEX_REFUSED,
                                    u"this type could not be made current"))
                continue
            for name, minimum, maximum in specs:
                param = None
                try:
                    param = manager.get_Parameter(name)
                except Exception:
                    param = None
                if param is None:
                    rows.append(FlexRow(type_name, name, u"",
                                        fet_core.FLEX_REFUSED,
                                        u"it is no longer in the family"))
                    continue
                for value in fet_core.flex_values(minimum, maximum, steps):
                    status, message = _flex_once(doc, manager, param, value,
                                                 catcher)
                    rows.append(FlexRow(type_name, name, value, status,
                                        message))
    finally:
        try:
            group.RollBack()
        except Exception:
            results.append(Result(FAILED, u"putting the family back",
                                  u"the run could not be undone - close "
                                  u"this family WITHOUT saving"))
        try:
            if started is not None:
                manager.CurrentType = started
        except Exception:
            pass

    worst = fet_core.flex_worst(rows)
    results.append(Result(
        CREATED if worst == fet_core.FLEX_OK else SKIPPED,
        u"{0} types, {1} rounds".format(len(types), len(rows)),
        fet_core.flex_summary(rows) + u" - nothing was left changed"))
    return rows, results
