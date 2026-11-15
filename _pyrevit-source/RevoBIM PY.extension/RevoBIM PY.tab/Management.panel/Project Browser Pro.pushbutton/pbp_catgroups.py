# -*- coding: utf-8 -*-
u"""Project Browser Pro - the main groups the Families tab opens with.

    Tags                    every tag of every category
    Annotations             dimensions, symbols, detail items, title blocks...
    Architecture            architectural categories
    Structure               structural categories
    Electrical              every electrical category
    Mechanical & Plumbing   ductwork, pipework, plumbing, sprinklers, fabrication
    Other                   the rest

A category used by both architecture and MEP (plumbing fixtures, lighting
fixtures, mechanical equipment...) sits in its MEP group, never in
Architecture or Structure.

Categories are matched by their BuiltInCategory name first (OST_...), which
is the same in every language Revit runs in, then by their English name -
a category added in a later Revit, or a name we have no OST for, still
lands somewhere sensible. Pure Python: the bench runs a table of real
category names through it.
"""
from pbp_compat import to_text

TAGS = u'Tags'
ANNOTATIONS = u'Annotations'
ARCHITECTURE = u'Architecture'
STRUCTURE = u'Structure'
ELECTRICAL = u'Electrical'
MECHANICAL = u'Mechanical & Plumbing'
OTHER = u'Other'

# The order the groups appear in - not alphabetical.
ORDER = (TAGS, ANNOTATIONS, ARCHITECTURE, STRUCTURE, ELECTRICAL, MECHANICAL, OTHER)

# Colour family of each group's gradient (pbp_palette.RAMPS).
RAMP = {ELECTRICAL: u'electrical', MECHANICAL: u'mechanical'}

# Icons on the 12 x 12 grid, drawn like the row icons.
ICONS = {
    # a luggage tag with its eyelet
    TAGS: u'F0 M1,3 L7.5,3 L11.2,6 L7.5,9 L1,9 Z M7,6 A1,1 0 1 0 9,6 A1,1 0 1 0 7,6 Z',
    # a dimension: two extension lines and an arrowed line between them
    ANNOTATIONS: u'M0.8,2 L2,2 L2,10 L0.8,10 Z M10,2 L11.2,2 L11.2,10 L10,10 Z '
                 u'M2,6 L4.4,4 L4.4,5.4 L7.6,5.4 L7.6,4 L10,6 L7.6,8 L7.6,6.6 L4.4,6.6 L4.4,8 Z',
    # a house
    ARCHITECTURE: u'F0 M6,0.8 L11.4,5.6 L10,5.6 L10,11.2 L2,11.2 L2,5.6 L0.6,5.6 Z '
                  u'M4.8,7 L7.2,7 L7.2,11.2 L4.8,11.2 Z',
    # an I-beam end on
    STRUCTURE: u'M1,1 L11,1 L11,3 L7,3 L7,9 L11,9 L11,11 L1,11 L1,9 L5,9 L5,3 L1,3 Z',
    # a lightning bolt
    ELECTRICAL: u'M7,0.5 L2.2,6.8 L5.4,6.8 L4.4,11.5 L9.8,4.8 L6.6,4.8 Z',
    # a duct with a pipe beneath it
    MECHANICAL: u'F0 M0.5,1 L11.5,1 L11.5,6 L0.5,6 Z M2,2.4 L10,2.4 L10,4.6 L2,4.6 Z '
                u'M0.5,8 L11.5,8 L11.5,10.6 L0.5,10.6 Z',
    # three dots
    OTHER: u'M0.8,6 A1.5,1.5 0 1 0 3.8,6 A1.5,1.5 0 1 0 0.8,6 Z '
           u'M4.5,6 A1.5,1.5 0 1 0 7.5,6 A1.5,1.5 0 1 0 4.5,6 Z '
           u'M8.2,6 A1.5,1.5 0 1 0 11.2,6 A1.5,1.5 0 1 0 8.2,6 Z',
}

ELECTRICAL_OST = set(u'''CableTray CableTrayFitting CableTrayRun CableTrayRunCenterLine
CableTrayFittingCenterLine CableTrayCenterLine Conduit ConduitFitting ConduitRun
ConduitCenterLine ConduitFittingCenterLine CommunicationDevices DataDevices
ElectricalEquipment ElectricalFixtures FireAlarmDevices LightingDevices
LightingFixtures NurseCallDevices SecurityDevices TelephoneDevices Wire
WireInsulations WireMaterials WireTemperatureRatings ElectricalCircuit
ElectricalDemandFactor ElectricalLoadClassifications ElecDistributionSys
ElectricalVoltage ElectricalInternalCircuits FabricationContainment
AudioVisualDevices ElectricalAnalyticalBus ElectricalAnalyticalLoadSet
ElectricalAnalyticalTransferSwitch ElectricalAnalyticalTransformer
ElectricalPowerSource ElectricalCircuitNaming SwitchSystem
ElectricalSpareSpaceCircuits'''.split())

MECHANICAL_OST = set(u'''DuctTerminal DuctAccessory DuctFitting DuctInsulations
DuctLinings DuctCurves PlaceHolderDucts FlexDuctCurves DuctSystem DuctCurvesCenterLine
DuctFittingCenterLine FlexDuctCurvesCenterLine MechanicalEquipment
MechanicalControlDevices MechanicalEquipmentSet FabricationDuctwork
FabricationDuctworkStiffeners FabricationHangers FabricationPipework PipeAccessory
PipeFitting PipeInsulations PipeCurves PlaceHolderPipes FlexPipeCurves PipingSystem
PipeCurvesCenterLine PipeFittingCenterLine FlexPipeCurvesCenterLine PipeSegments
PlumbingFixtures PlumbingEquipment Sprinklers FireProtection HVAC_Zones MEPSpaces
ZoneEquipment MEPAnalyticalAirLoop MEPAnalyticalWaterLoop MechanicalLoadType
MEPLoadAreas MEPLoadAreaSeparationLines'''.split())

ARCHITECTURE_OST = set(u'''Walls Doors Windows Floors Roofs Ceilings Stairs StairsRuns
StairsLandings StairsSupports StairsRailing StairsRailingBaluster RailingTopRail
RailingHandRail RailingSupport RailingTermination Ramps CurtainWallPanels
CurtainWallMullions CurtaSystem Columns Furniture FurnitureSystems Casework Planting
Entourage Site Parking Topography Toposolid Roads Hardscape SpecialityEquipment Mass
Rooms Areas FoodServiceEquipment MedicalEquipment Signage VerticalCirculation Fascia
Gutter Cornices RoofSoffit EdgeSlab Reveals ShaftOpening BuildingPad
TemporaryStructure Railings Stairs ElevatorShaft ExpansionJoints'''.split())

STRUCTURE_OST = set(u'''Rebar AreaRein PathRein FabricReinforcement FabricAreas Coupler
RebarShape BeamSystem Truss StructuralFramingSystem StructConnectionPlates
StructConnectionBolts StructConnectionAnchors StructConnectionWelds
StructConnectionShearStuds StructConnectionHoles StructConnectionProfiles
StructConnections FoundationSlab IsolatedFoundation WallFoundation
StructuralTendons'''.split())

ANNOTATION_OST = set(u'''DetailComponents TitleBlocks GenericAnnotation RevisionClouds
Dimensions TextNotes SpotElevations SpotCoordinates SpotSlopes ViewTitles
SectionHeads ElevationMarks CalloutHeads LevelHeads GridHeads ReferenceViewerSymbol
MatchlineHeads RepeatingDetailComponent FilledRegion MaskingRegion
SpanDirectionSymbol MultiReferenceAnnotations InsulationLines'''.split())

# English names, for a category with no OST name we know.
ELECTRICAL_WORDS = (u'cable tray', u'conduit', u'electrical', u'lighting', u'fire alarm',
                    u'security device', u'communication device', u'data device',
                    u'telephone device', u'nurse call', u'wire', u'fabrication containment',
                    u'audio visual')
MECHANICAL_WORDS = (u'duct', u'pipe', u'piping', u'plumbing', u'mechanical', u'sprinkler',
                    u'air terminal', u'fabrication ductwork', u'fabrication pipework',
                    u'fabrication hanger', u'fire protection', u'hvac', u'space')
ARCHITECTURE_WORDS = (u'wall', u'door', u'window', u'floor', u'roof', u'ceiling', u'stair',
                      u'railing', u'ramp', u'curtain', u'column', u'furniture', u'casework',
                      u'planting', u'entourage', u'site', u'parking', u'topography',
                      u'toposolid', u'road', u'hardscape', u'specialty equipment', u'mass',
                      u'room', u'area', u'food service', u'medical equipment', u'signage',
                      u'vertical circulation', u'fascia', u'gutter', u'soffit', u'slab edge')
ANNOTATION_WORDS = (u'detail item', u'title block', u'annotation', u'revision cloud',
                    u'dimension', u'symbol', u'view title', u'level head', u'grid head',
                    u'callout head', u'section head', u'elevation mark', u'spot ')


def ost_name(text):
    u"""'OST_CableTray' or 'CableTray' -> 'CableTray'."""
    text = to_text(text).strip()
    return text[4:] if text.startswith(u'OST_') else text


def _has(name, words):
    u"""True when a word in the list starts a word of the name (so 'site'
    finds Site but not Composite)."""
    name = u' ' + name.lower() + u' '
    return any((u' ' + word) in name for word in words)


def main_group(ost, name, category_type=u''):
    u"""The main group label for a category.

    ost: BuiltInCategory name (with or without OST_), or u''.
    name: the category's name as Revit shows it.
    category_type: 'Model', 'Annotation', ... as Revit reports it.
    """
    key = ost_name(ost)
    name = to_text(name).strip()
    lower = name.lower()
    # Tags first - a Duct Tag is a tag before it is anything mechanical.
    if key.endswith(u'Tags') or key.endswith(u'Tag') or lower.endswith(u' tags') \
            or lower.endswith(u' tag') or lower == u'tags':
        return TAGS
    if key in ELECTRICAL_OST:
        return ELECTRICAL
    if key in MECHANICAL_OST:
        return MECHANICAL
    if key in STRUCTURE_OST or key.startswith(u'Struct'):
        return STRUCTURE
    if key in ARCHITECTURE_OST:
        return ARCHITECTURE
    if key in ANNOTATION_OST:
        return ANNOTATIONS
    if key:
        # a known OST we have not placed: its kind decides
        return ANNOTATIONS if to_text(category_type) == u'Annotation' else OTHER
    # no OST name: go by the English name
    if lower.startswith(u'structural') or lower in (u'rebar', u'plates', u'bolts',
                                                    u'anchors', u'welds', u'shear studs'):
        return STRUCTURE
    if _has(name, ELECTRICAL_WORDS):
        return ELECTRICAL
    if _has(name, MECHANICAL_WORDS):
        return MECHANICAL
    if _has(name, ANNOTATION_WORDS) or to_text(category_type) == u'Annotation':
        return ANNOTATIONS
    if _has(name, ARCHITECTURE_WORDS):
        return ARCHITECTURE
    return OTHER


def icon(group):
    return ICONS.get(group)


def ramp(group):
    u"""Which colour gradient a group (and its categories) is drawn in."""
    return RAMP.get(group, u'other')
