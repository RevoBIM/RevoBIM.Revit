# -*- coding: utf-8 -*-
"""Everything that touches the model: reading the tags, working out where the
elbow goes, and the single transaction that writes them."""

import tle_clr  # noqa: F401  assemblies first, always

from Autodesk.Revit.DB import (XYZ, Transaction, TransactionStatus, SubTransaction,
                               ElementId, IndependentTag, SpatialElementTag,
                               BuiltInParameter, LocationPoint, LocationCurve)
from Autodesk.Revit.UI.Selection import ObjectType, ISelectionFilter

import tle_core

# ============================================================================
# selection
# ============================================================================

class TagFilter(ISelectionFilter):
    """Tags only, so a stray pipe cannot get into the pick."""

    def __init__(self, include_spatial):
        self.include_spatial = include_spatial

    def AllowElement(self, element):
        try:
            if isinstance(element, IndependentTag):
                return True
            if self.include_spatial and isinstance(element, SpatialElementTag):
                return True
        except Exception:
            pass
        return False

    def AllowReference(self, reference, point):
        return False


def gather_tags(uidoc, cfg):
    """Whatever is selected, filtered to tags.  Nothing selected asks for them."""
    doc = uidoc.Document
    include_spatial = tle_core.as_bool(cfg, "include_spatial_tags")

    tags = []
    others = 0
    for element_id in uidoc.Selection.GetElementIds():
        element = doc.GetElement(element_id)
        if isinstance(element, IndependentTag):
            tags.append(element)
        elif include_spatial and isinstance(element, SpatialElementTag):
            tags.append(element)
        else:
            others += 1

    if tags:
        return tags, others, None

    if not tle_core.as_bool(cfg, "prompt_when_empty"):
        return [], others, "Nothing tag-shaped was selected."

    try:
        picked = uidoc.Selection.PickObjects(
            ObjectType.Element, TagFilter(include_spatial),
            "Pick the tags to put a leader elbow on, then Finish")
    except Exception:
        return [], others, None  # Escape: leave without a word

    for reference in picked:
        element = doc.GetElement(reference.ElementId)
        if element is not None:
            tags.append(element)
    return tags, others, None


# ============================================================================
# geometry helpers
# ============================================================================

def view_of(doc, tag):
    try:
        return doc.GetElement(tag.OwnerViewId)
    except Exception:
        return None


def view_scale(view):
    try:
        scale = view.Scale
        if scale and scale > 0:
            return scale
    except Exception:
        pass
    return 100


def right_direction(view):
    """The view's own horizontal.  Elbowing 'horizontally' means along this."""
    try:
        direction = view.RightDirection
        if direction is not None and direction.GetLength() > 1e-9:
            return direction.Normalize()
    except Exception:
        pass
    return XYZ(1, 0, 0)


def up_direction(view):
    """The view's own vertical, so the drop onto the tag's centre is square to
    the leg rather than to the world."""
    try:
        direction = view.UpDirection
        if direction is not None and direction.GetLength() > 1e-9:
            return direction.Normalize()
    except Exception:
        pass
    return XYZ(0, 1, 0)


def tagged_references(tag):
    """Every leader on the tag.  Multi-reference tags arrived in 2022; the
    property route is kept for anything that will not answer."""
    try:
        refs = list(tag.GetTaggedReferences())
        if refs:
            return refs
    except Exception:
        pass
    return [None]


def has_leader(tag):
    try:
        return bool(tag.HasLeader)
    except Exception:
        return True


def has_elbow(tag, reference):
    if reference is not None:
        try:
            return bool(tag.HasLeaderElbow(reference))
        except Exception:
            pass
    try:
        return tag.LeaderElbow is not None
    except Exception:
        return False


def element_point(doc, tag, reference):
    """Where the leader lands when it is attached rather than free ended."""
    try:
        element_id = reference.ElementId if reference is not None else ElementId.InvalidElementId
        linked_id = None
        try:
            linked_id = reference.LinkedElementId
        except Exception:
            linked_id = None

        source_doc = doc
        transform = None
        if linked_id is not None and tle_core.eid_value(linked_id) > 0:
            link = doc.GetElement(element_id)
            try:
                source_doc = link.GetLinkDocument()
                transform = link.GetTotalTransform()
            except Exception:
                source_doc = doc
                transform = None
            element_id = linked_id

        element = source_doc.GetElement(element_id)
        point = None
        location = getattr(element, "Location", None)
        if isinstance(location, LocationPoint):
            point = location.Point
        elif isinstance(location, LocationCurve):
            curve = location.Curve
            point = curve.Evaluate(0.5, True)
        if point is None:
            box = element.get_BoundingBox(None)
            if box is not None:
                point = (box.Min + box.Max) / 2.0
        if point is not None and transform is not None:
            point = transform.OfPoint(point)
        return point
    except Exception:
        return None


def leader_anchor(doc, tag, reference):
    """The far end of this leader, however Revit is willing to give it up.

    Order: the free leader end, then the tag's own single-leader property,
    then the existing elbow, then the tagged element's own position.  The
    last of those covers an attached-end leader, where GetLeaderEnd throws.
    """
    if reference is not None:
        try:
            point = tag.GetLeaderEnd(reference)
            if point is not None:
                return point, "leader end"
        except Exception:
            pass
    try:
        point = tag.LeaderEnd
        if point is not None:
            return point, "leader end"
    except Exception:
        pass
    if reference is not None:
        try:
            point = tag.GetLeaderElbow(reference)
            if point is not None:
                return point, "existing elbow"
        except Exception:
            pass
    try:
        point = tag.LeaderElbow
        if point is not None:
            return point, "existing elbow"
    except Exception:
        pass
    point = element_point(doc, tag, reference)
    if point is not None:
        return point, "tagged element"
    return None, None


# ============================================================================
# how wide the tag's own text is
# ============================================================================

def _type_double(element, built_in, fallback):
    try:
        parameter = element.get_Parameter(built_in)
        if parameter is not None:
            value = parameter.AsDouble()
            if value:
                return value
    except Exception:
        pass
    return fallback


def _type_string(element, built_in, fallback):
    try:
        parameter = element.get_Parameter(built_in)
        if parameter is not None:
            value = parameter.AsString()
            if value:
                return value
    except Exception:
        pass
    return fallback


def _type_flag(element, built_in):
    try:
        parameter = element.get_Parameter(built_in)
        if parameter is not None:
            return bool(parameter.AsInteger())
    except Exception:
        pass
    return False


def tag_text(tag):
    for name in ("TagText", "Name"):
        try:
            value = getattr(tag, name)
            if value:
                return value
        except Exception:
            pass
    return ""


def _measure_with_wpf(text, font, bold, italic):
    """The width of the string at an em size of 100, so the caller can scale it.

    WPF is already loaded for the windows, so it is the one real text
    measurement available without a font table of our own.  The FormattedText
    constructor gained a pixelsPerDip argument in .NET 4.6 and the older one is
    obsolete but still there in .NET 8, so both shapes are tried: Revit 2024 is
    .NET Framework 4.8 and 2025 and later are .NET 8.
    """
    from System.Windows.Media import FormattedText, Typeface, Brushes
    from System.Windows import FlowDirection, FontStyles, FontWeights, FontStretches
    from System.Globalization import CultureInfo

    weight = FontWeights.Bold if bold else FontWeights.Normal
    style = FontStyles.Italic if italic else FontStyles.Normal
    typeface = Typeface(font)
    try:
        typeface = Typeface(FontFamilyFor(font), style, weight, FontStretches.Normal)
    except Exception:
        pass

    lines = str(text).splitlines() or [str(text)]
    widest = 0.0
    pitch = 0.0
    for line in lines:
        formatted = None
        try:
            formatted = FormattedText(line, CultureInfo.InvariantCulture,
                                      FlowDirection.LeftToRight, typeface, 100.0,
                                      Brushes.Black, 1.0)
        except Exception:
            formatted = FormattedText(line, CultureInfo.InvariantCulture,
                                      FlowDirection.LeftToRight, typeface, 100.0,
                                      Brushes.Black)
        if formatted.Width > widest:
            widest = formatted.Width
        if formatted.Height > pitch:
            pitch = formatted.Height
    return widest / 100.0, pitch / 100.0, len(lines)


def FontFamilyFor(name):
    from System.Windows.Media import FontFamily
    return FontFamily(name)


def tag_text_metrics(doc, tag, view, cfg):
    """(width, line pitch, line count, how it was worked out), in feet of model.

    Text size on a tag type is a paper measurement held in internal feet, so
    the model width is that times the view scale.  Revit has no API for the
    extent of a tag's text, and the tag's own bounding box includes its leader,
    which is exactly the thing being moved, so it is measured from the string
    instead.
    """
    text = tag_text(tag)
    if not text:
        return 0.0, 0.0, 1, "no tag text to measure"

    tag_type = None
    try:
        tag_type = doc.GetElement(tag.GetTypeId())
    except Exception:
        tag_type = None
    if tag_type is None:
        return 0.0, 0.0, 1, "the tag type could not be read"

    size_ft = _type_double(tag_type, BuiltInParameter.TEXT_SIZE, tle_core.mm_to_ft(2.5))
    factor = _type_double(tag_type, BuiltInParameter.TEXT_WIDTH_SCALE, 1.0)
    font = _type_string(tag_type, BuiltInParameter.TEXT_FONT, "Arial")
    bold = _type_flag(tag_type, BuiltInParameter.TEXT_STYLE_BOLD)
    italic = _type_flag(tag_type, BuiltInParameter.TEXT_STYLE_ITALIC)
    scale = view_scale(view)

    lines = len(str(text).splitlines() or [str(text)])
    source = "measured"
    ems = None
    pitch_ems = None
    try:
        ems, pitch_ems, lines = _measure_with_wpf(text, font, bold, italic)
    except Exception:
        ems = None
    if not ems:
        source = "estimated"
        ems = tle_core.estimate_text_width_mm(
            text, 1.0, 1.0, tle_core.as_float(cfg, "glyph_width", floor=0.05))
        pitch_ems = tle_core.as_float(cfg, "line_pitch", floor=0.5)

    paper = size_ft * factor * scale
    line_ft = (pitch_ems or 1.2) * size_ft * scale
    return ems * paper, line_ft, lines, source


# ============================================================================
# the tag's own extent, with its leader taken out of the way
# ============================================================================

def _corners(box):
    low, high = box.Min, box.Max
    points = []
    for x in (low.X, high.X):
        for y in (low.Y, high.Y):
            for z in (low.Z, high.Z):
                points.append(XYZ(x, y, z))
    return points


def measure_tag_boxes(doc, tags):
    """The extent of every tag, measured with its leader switched off.

    A tag's bounding box normally includes its leader, which is the thing being
    moved, so the box is useless as it stands.  Switching the leaders off inside
    a **sub-transaction that is then rolled back** gives the box of the tag
    alone and leaves the model exactly as it was: the rollback is the whole
    point, and it is why this is safe to do to somebody's drawing.

    All the tags are done in one sub-transaction with one regenerate, because a
    regenerate per tag is the difference between a second and a minute on a
    drawing's worth of tags.

    Returns {element id: (up min, up max, right min, right max)}, each measured
    from that tag's own head along its own view's axes.
    """
    wanted = []
    for tag in tags:
        view = view_of(doc, tag)
        head = head_position(tag) if not isinstance(tag, SpatialElementTag) \
            else spatial_pair(tag)[0]
        if view is None or head is None:
            continue
        if not has_leader(tag):
            continue
        wanted.append((tag, view, head))
    if not wanted:
        return {}

    boxes = {}
    sub = SubTransaction(doc)
    try:
        sub.Start()
    except Exception:
        return {}
    try:
        switched = []
        for tag, view, head in wanted:
            try:
                tag.HasLeader = False
                switched.append(tag)
            except Exception:
                pass
        if not switched:
            sub.RollBack()
            return {}
        doc.Regenerate()
        for tag, view, head in wanted:
            try:
                box = tag.get_BoundingBox(view)
                if box is None:
                    continue
                up = up_direction(view)
                right = right_direction(view)
                ups = []
                rights = []
                for corner in _corners(box):
                    offset = corner - head
                    ups.append(offset.DotProduct(up))
                    rights.append(offset.DotProduct(right))
                boxes[tle_core.eid_value(tag.Id)] = (
                    min(ups), max(ups), min(rights), max(rights))
            except Exception:
                continue
    except Exception:
        boxes = {}
    try:
        sub.RollBack()
    except Exception:
        pass
    return boxes


def head_position(tag):
    for name in ("TagHeadPosition", "LeaderElbowPosition"):
        try:
            point = getattr(tag, name)
            if point is not None and name == "TagHeadPosition":
                return point
        except Exception:
            pass
    return None


def set_elbow(tag, reference, point):
    """SetLeaderElbow where the release offers it, the property otherwise."""
    errors = []
    if reference is not None:
        try:
            tag.SetLeaderElbow(reference, point)
            return True, None
        except Exception as error:
            errors.append(str(error))
    try:
        tag.LeaderElbow = point
        return True, None
    except Exception as error:
        errors.append(str(error))
    return False, errors[-1] if errors else "Revit would not take the elbow"


# ============================================================================
# spatial tags (room and space tags) take a different route
# ============================================================================

def spatial_pair(tag):
    """(head, anchor) for a room or space tag, or (None, None)."""
    head = None
    anchor = None
    try:
        location = tag.Location
        if isinstance(location, LocationPoint):
            head = location.Point
    except Exception:
        pass
    try:
        anchor = tag.LeaderEnd
    except Exception:
        anchor = None
    if anchor is None:
        try:
            anchor = tag.LeaderElbowPosition
        except Exception:
            anchor = None
    return head, anchor


def set_spatial_elbow(tag, point):
    try:
        tag.LeaderElbowPosition = point
        return True, None
    except Exception as error:
        return False, str(error)


# ============================================================================
# the run
# ============================================================================

class Row(object):
    def __init__(self, kind, label, note):
        self.kind = kind
        self.label = label
        self.note = note

    def as_tuple(self):
        return (self.kind, self.label, self.note)


def label_for(doc, tag):
    try:
        name = tag.Name
    except Exception:
        name = "Tag"
    return "{0}  [{1}]".format(name, tle_core.eid_value(tag.Id))


def plan_and_write(doc, tags, cfg):
    """One transaction for the whole run, so a failure rolls back cleanly."""
    rows = []
    done = 0
    skipped = 0
    failed = 0

    transaction = Transaction(doc, "RevoBIM Tag Leader Elbow")
    transaction.Start()
    try:
        boxes = {}
        if cfg.get("tag_extent", "measured") == "measured":
            try:
                boxes = measure_tag_boxes(doc, tags)
            except Exception:
                boxes = {}

        for tag in tags:
            view = view_of(doc, tag)
            if view is None:
                rows.append(Row("fail", label_for(doc, tag),
                                "its own view could not be read"))
                failed += 1
                continue

            right = right_direction(view)
            scale = view_scale(view)
            length = tle_core.elbow_length_ft(cfg, scale)
            was_pinned = False
            try:
                was_pinned = bool(tag.Pinned)
            except Exception:
                was_pinned = False
            if was_pinned:
                if not tle_core.as_bool(cfg, "unpin"):
                    rows.append(Row("skip", label_for(doc, tag), "pinned, left alone"))
                    skipped += 1
                    continue
                try:
                    tag.Pinned = False
                except Exception:
                    pass

            try:
                box = boxes.get(tle_core.eid_value(tag.Id))
                if isinstance(tag, SpatialElementTag):
                    outcome = _do_spatial(doc, tag, view, right, length, cfg, box)
                else:
                    outcome = _do_independent(doc, tag, view, right, length, cfg, box)
            finally:
                if was_pinned:
                    try:
                        tag.Pinned = True
                    except Exception:
                        pass

            for row in outcome:
                rows.append(row)
                if row.kind == "done":
                    done += 1
                elif row.kind == "skip":
                    skipped += 1
                else:
                    failed += 1

        status = transaction.Commit()
        if status != TransactionStatus.Committed:
            rows.append(Row("fail", "The transaction",
                            "Revit reported {0} rather than a commit".format(status)))
            failed += 1
            done = 0
    except Exception as error:
        try:
            transaction.RollBack()
        except Exception:
            pass
        rows.append(Row("fail", "The run", "rolled back: {0}".format(error)))
        failed += 1
        done = 0

    return rows, done, skipped, failed


def _do_independent(doc, tag, view, right, length, cfg, box=None):
    rows = []
    label = label_for(doc, tag)

    if not has_leader(tag):
        return [Row("skip", label, "no leader turned on")]

    head = head_position(tag)
    if head is None:
        return [Row("fail", label, "the tag head position could not be read")]

    up = up_direction(view)
    width = line_ft = 0.0
    lines = 1
    if box is None:
        width, line_ft, lines, _ = tag_text_metrics(doc, tag, view, cfg)
    references = tagged_references(tag)
    multi = len(references) > 1

    for index, reference in enumerate(references):
        this_label = label if not multi else "{0}  leader {1}".format(label, index + 1)
        anchor, source = leader_anchor(doc, tag, reference)
        along = None
        if anchor is not None:
            along = (anchor - head).DotProduct(right)

        sign, reason = tle_core.decide(True, along, has_elbow(tag, reference), cfg)
        if sign == 0:
            rows.append(Row("skip", this_label, reason))
            continue

        target, offset, ahead, drop, how = _place(
            head, up, right, sign, length, box, width, line_ft, lines, cfg)
        ok, error = set_elbow(tag, reference, target)
        if not ok:
            rows.append(Row("fail", this_label, "Revit refused the elbow: {0}".format(error)))
            continue

        note = _note(length, offset, ahead, drop, sign, source, how)
        moved = _restore_head(tag, head, cfg)
        if moved:
            note = note + "; the head was put back"
        rows.append(Row("done", this_label, note))

    if not rows:
        rows.append(Row("skip", label, "no leader references to work with"))
    return rows


def _place(head, up, right, sign, length, box, width, line_ft, lines, cfg):
    """Where the elbow goes, and how it was worked out.

    Measured comes first: the tag's own extent gives the exact vertical middle
    Revit runs the leader into, and the exact width on the side the leg goes,
    with no assumption about justification or how many lines there are.  The
    text measurement is the fallback for a tag whose box could not be read.
    """
    centre = tle_core.centre_from_box_ft(box)
    ahead = tle_core.ahead_from_box_ft(box, sign, cfg)
    if centre is not None and ahead is not None:
        how = "measured off the tag"
        drop = centre
    else:
        how = "worked out from the tag text"
        drop = tle_core.vertical_shift_ft(line_ft, lines, cfg)
        ahead = tle_core.text_ahead_ft(width, sign, cfg)

    if cfg.get("start_from", "edge") == "head":
        ahead = 0.0
    offset = ahead + length
    return head + up.Multiply(drop) + right.Multiply(offset * sign), offset, ahead, drop, how


def _note(length, offset, ahead, drop, sign, source, how):
    side = "right" if sign > 0 else "left"
    parts = ["{0}mm {1} of {2}mm of tag ({3}), {4}mm from the head".format(
        int(round(tle_core.ft_to_mm(length))), side,
        int(round(tle_core.ft_to_mm(ahead))), how,
        int(round(tle_core.ft_to_mm(offset))))]
    if drop:
        parts.append("{0} {1}mm onto the tag's middle".format(
            "dropped" if drop < 0 else "raised",
            int(round(abs(tle_core.ft_to_mm(drop))))))
    parts.append("side from the " + (source or "leader"))
    return ", ".join(parts)


def _do_spatial(doc, tag, view, right, length, cfg, box=None):
    label = "{0}  [{1}]".format(getattr(tag, "TagText", "Room tag"),
                                tle_core.eid_value(tag.Id))
    if not has_leader(tag):
        return [Row("skip", label, "no leader turned on")]

    head, anchor = spatial_pair(tag)
    if head is None:
        return [Row("fail", label, "the tag head position could not be read")]

    up = up_direction(view)
    width = line_ft = 0.0
    lines = 1
    if box is None:
        width, line_ft, lines, _ = tag_text_metrics(doc, tag, view, cfg)

    along = None
    if anchor is not None:
        along = (anchor - head).DotProduct(right)

    sign, reason = tle_core.decide(True, along, anchor is not None, cfg)
    if sign == 0:
        return [Row("skip", label, reason)]

    target, offset, ahead, drop, how = _place(
        head, up, right, sign, length, box, width, line_ft, lines, cfg)
    ok, error = set_spatial_elbow(tag, target)
    if not ok:
        return [Row("fail", label, "Revit refused the elbow: {0}".format(error))]
    return [Row("done", label, _note(length, offset, ahead, drop, sign, "leader", how))]


def _restore_head(tag, head, cfg):
    """The tag is not to move.  Setting an elbow should not shift the head, but
    if a release does nudge it, put it back rather than leave it moved."""
    if not tle_core.as_bool(cfg, "keep_head_fixed"):
        return False
    try:
        now = tag.TagHeadPosition
        if now is None:
            return False
        if now.DistanceTo(head) < tle_core.mm_to_ft(0.05):
            return False
        tag.TagHeadPosition = head
        return True
    except Exception:
        return False
