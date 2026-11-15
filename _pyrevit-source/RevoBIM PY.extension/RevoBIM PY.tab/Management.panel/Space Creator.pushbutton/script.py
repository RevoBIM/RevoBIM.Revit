# -*- coding: utf-8 -*-
"""Space Creator
One tool, two tabs.

  Automatic - places MEP spaces into every room in the current view or the
              whole project.
  Manual    - pick rooms in a linked model and place a host space in each.

Shared across both: separation-line stitching, push to the underside of
the floor above, room name inheritance and workset assignment.

The window is modeless so the Manual tab can pick in the model while it is
open, which means every write - including the Automatic tab's - has to go
out through an ExternalEvent. A modeless window cannot start a transaction
directly.
"""

__title__ = "Space Creator"
__author__ = "RevoBIM PY"
__version__ = "3.1.0"

import os
import sys
import traceback
import clr

clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("WindowsBase")
clr.AddReference("RevitAPI")
clr.AddReference("RevitAPIUI")

from System import Action
from System.Windows.Markup import XamlReader
from System.Windows.Interop import WindowInteropHelper
from System.Windows.Threading import DispatcherPriority
from System.Windows.Controls import (Grid, ColumnDefinition, TextBlock,
                                     TextBox, ListBoxItem, Border)
from System.Windows import (GridLength, GridUnitType, Thickness, Visibility,
                            FontWeights, VerticalAlignment)
from System.Windows.Media import SolidColorBrush, ColorConverter
from System.Windows import TextTrimming

from Autodesk.Revit.DB import (
    Transaction,
    TransactionGroup,
    Level,
    FilteredElementCollector,
    Category,
    BuiltInCategory,
)
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent, TaskDialog
from Autodesk.Revit.UI.Selection import (PickBoxStyle, ObjectType,
                                         ISelectionFilter)
from Autodesk.Revit.DB.Architecture import Room


class LinkedRoomFilter(ISelectionFilter):
    """Allows only rooms inside Revit links.

    Rooms in a link **are** selectable in Revit - Tab cycles to them under
    the cursor and they highlight like anything else. Earlier versions of
    this tool concluded they were not, and rebuilt selection twice around
    that assumption; what was actually happening was that the pick
    succeeded and the room was thrown away afterwards on `room.Name`
    (fixed in 2.11.0)."""

    def AllowElement(self, element):
        # The candidate handed here is the link instance; the reference
        # check below is what narrows it to rooms.
        return True

    def AllowReference(self, reference, position):
        try:
            link_instance = doc.GetElement(reference.ElementId)
            link_doc = link_instance.GetLinkDocument()
            if link_doc is None:
                return False
            linked_element = link_doc.GetElement(reference.LinkedElementId)
            return isinstance(linked_element, Room)
        except Exception:
            return False


class HostRoomFilter(ISelectionFilter):
    """Allows only rooms in this document."""

    def AllowElement(self, element):
        try:
            return isinstance(element, Room)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return True
from Autodesk.Revit.Exceptions import OperationCanceledException

from pyrevit import revit, script

__persistentengine__ = True

# --- make the shared lib importable (RevoBIM PY.extension/lib) -------------
THIS_DIR = os.path.dirname(__file__)
EXTENSION_LIB = os.path.abspath(os.path.join(THIS_DIR, "..", "..", "..", "lib"))
if EXTENSION_LIB not in sys.path:
    sys.path.append(EXTENSION_LIB)

from revobim import space_creator_core as core
from revobim import theme

logger = script.get_logger()

doc = revit.doc
uidoc = revit.uidoc

# The window is parked at module level: without a reference held here the
# persistent engine can collect a modeless window out from under the user.
_window = None

picked_rooms = []

NONE_WORKSET = "(none - do not assign)"

# Rooms per transaction. Small enough that the progress bar moves and one
# refused room cannot roll back hundreds of good ones, large enough that
# the commits themselves are not the cost.
CHUNK_SIZE = 25

_brush_cache = {}


def _brush(hex_colour):
    """SolidColorBrush from a hex string, cached and frozen."""
    if hex_colour in _brush_cache:
        return _brush_cache[hex_colour]
    try:
        brush = SolidColorBrush(ColorConverter.ConvertFromString(hex_colour))
        brush.Freeze()
    except Exception:
        brush = None
    _brush_cache[hex_colour] = brush
    return brush


# ---------------------------------------------------------------------------
# XAML
#
# TabItem and the other surface-rendering controls carry full control
# templates: WPF's stock TabItem ignores Background and falls back to the
# system theme, which reads as white tabs on a dark window. Styles are
# implicit (TargetType with no key) so nothing has to be resolved by key.
# ---------------------------------------------------------------------------

XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM Space Creator"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" ResizeMode="CanResize"
        SizeToContent="Manual" Width="860" Height="720"
        MinWidth="620" MinHeight="420" ShowInTaskbar="True">

  <Window.Resources>

    <!--SCROLLBARS-->

    <Style TargetType="TabItem">
      <Setter Property="Foreground" Value="{TEXT_MUTED}"/>
      <Setter Property="FontSize" Value="12.5"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TabItem">
            <Border Name="Chrome" Background="{CARD_BG}" BorderBrush="{BORDER}"
                    BorderThickness="1,1,1,0" CornerRadius="4,4,0,0"
                    Margin="0,0,3,0" Padding="16,7,16,7">
              <StackPanel>
                <ContentPresenter ContentSource="Header" HorizontalAlignment="Center"/>
                <Border Name="Underline" Height="2" Margin="0,5,0,-5"
                        Background="Transparent"/>
              </StackPanel>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsSelected" Value="True">
                <Setter TargetName="Chrome" Property="Background" Value="{WINDOW_BG}"/>
                <Setter TargetName="Underline" Property="Background" Value="{BLUE}"/>
                <Setter Property="Foreground" Value="{TEXT}"/>
                <Setter Property="FontWeight" Value="Bold"/>
              </Trigger>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter Property="Foreground" Value="{TEXT}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="TabControl">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="TabControl">
            <DockPanel>
              <TabPanel DockPanel.Dock="Top" IsItemsHost="True" Margin="0,0,0,0"/>
              <Border Background="{WINDOW_BG}" BorderBrush="{BORDER}" BorderThickness="1"
                      CornerRadius="0,4,4,4">
                <ContentPresenter ContentSource="SelectedContent"/>
              </Border>
            </DockPanel>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="CheckBox">
      <Setter Property="Foreground" Value="{TEXT}"/>
      <Setter Property="Margin" Value="0,4,0,4"/>
    </Style>

    <Style TargetType="RadioButton">
      <Setter Property="Foreground" Value="{TEXT}"/>
      <Setter Property="Margin" Value="0,4,0,4"/>
    </Style>

  </Window.Resources>

  <Grid>
   <Border CornerRadius="6" Background="{WINDOW_BG}" BorderBrush="#4A4A50" BorderThickness="1">
    <DockPanel LastChildFill="True">

      <!-- Header -->
      <Border DockPanel.Dock="Top" Background="{BAR_BG}" CornerRadius="6,6,0,0" Height="52" Name="HeaderBar">
        <Grid Margin="14,0,10,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <StackPanel Orientation="Vertical" VerticalAlignment="Center">
            <TextBlock Text="RevoBIM" FontSize="20" FontWeight="Bold" Foreground="{BLUE}"/>
            <TextBlock Text="Space Creator" FontSize="13" Foreground="{ORANGE}" Margin="0,-2,0,0"/>
          </StackPanel>
          <TextBlock Grid.Column="1" Text="v__VERSION__" Foreground="{TEXT_MUTED}" FontSize="11"
                     VerticalAlignment="Center" Margin="0,0,12,0"/>
          <Button Grid.Column="2" Name="CloseButton" Content="&#x2715;" Width="26" Height="26"
                  Background="Transparent" BorderThickness="0" Foreground="{TEXT_MUTED}" FontSize="13"
                  Cursor="Hand"/>
        </Grid>
      </Border>

      <!-- Progress band, collapsed until a run starts -->
      <Border DockPanel.Dock="Top" Name="ProgressPanel" Background="{CARD_BG}"
              Visibility="Collapsed" Padding="14,8,14,8">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <ProgressBar Name="RunProgressBar" Height="8" Minimum="0" Maximum="100" Value="0"
                       Background="{FIELD_BG}" Foreground="{BLUE}" BorderThickness="0"
                       VerticalAlignment="Center"/>
          <TextBlock Grid.Column="1" Name="ProgressText" Text="" Foreground="{TEXT_MUTED}"
                     FontSize="11" Margin="10,0,0,0" VerticalAlignment="Center"/>
        </Grid>
      </Border>

      <!-- Footer -->
      <Border DockPanel.Dock="Bottom" Background="{BAR_BG}" CornerRadius="0,0,6,6" Height="54">
        <Grid Margin="14,0,14,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <TextBlock Name="StatusText" Text="" Foreground="{TEXT_MUTED}" FontSize="11"
                     VerticalAlignment="Center" TextWrapping="Wrap" Grid.Column="0"
                     Margin="0,0,10,0"/>
          <Button Grid.Column="1" Name="ActionButton" Content="Place Spaces" Width="150" Height="32"
                  Background="{GREEN}" Foreground="White" BorderThickness="0" FontWeight="Bold" Cursor="Hand"/>
        </Grid>
      </Border>

      <!-- Body. A Grid, not a StackPanel: a StackPanel gives every child
           its natural height, so the tabs stayed their start size no
           matter how far the window was stretched. The star row hands the
           slack to the TabControl. -->
      <Grid Margin="18,14,18,10">
        <Grid.RowDefinitions>
          <RowDefinition Height="*"/>
          <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <TabControl Name="MainTabs" Grid.Row="0" Margin="0,0,0,14">

          <!-- ================= AUTOMATIC ================= -->
          <TabItem Name="TabAutomatic">
            <TabItem.Header>
              <StackPanel Orientation="Horizontal">
                <!-- Glyph: a room outline with a space placed in it.
                     Drawn from Borders, never a symbol font, so it cannot
                     come out as an empty box on a machine without it. -->
                <Grid Width="15" Height="15" VerticalAlignment="Center" Margin="0,0,7,0">
                  <Border BorderBrush="{BLUE}" BorderThickness="1.5" CornerRadius="2"/>
                  <Border Width="7" Height="7" CornerRadius="3.5" Background="{GREEN}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Grid>
                <TextBlock Text="Automatic" VerticalAlignment="Center"/>
              </StackPanel>
            </TabItem.Header>
            <StackPanel Margin="16,14,16,14">

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
                <TextBlock Text="ROOMS FROM" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                           VerticalAlignment="Center"/>
              </StackPanel>
              <StackPanel Orientation="Horizontal" Margin="12,0,0,14">
                <RadioButton Name="SourceBoth" GroupName="source" Content="This model + links"
                             Margin="0,0,16,0" IsChecked="True"/>
                <RadioButton Name="SourceHost" GroupName="source" Content="This model"
                             Margin="0,0,16,0"/>
                <RadioButton Name="SourceLinks" GroupName="source" Content="Links only"/>
              </StackPanel>

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
                <TextBlock Text="SCOPE" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                           VerticalAlignment="Center"/>
              </StackPanel>
              <StackPanel Orientation="Horizontal" Margin="12,0,0,14">
                <RadioButton Name="ScopeCurrentView" GroupName="scope" Content="Current view"
                             Margin="0,0,24,0" IsChecked="True"/>
                <RadioButton Name="ScopeAllProject" GroupName="scope" Content="All project"/>
              </StackPanel>

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{ORANGE}" Margin="0,0,8,0"/>
                <TextBlock Text="OPTIONS" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                           VerticalAlignment="Center"/>
              </StackPanel>
              <StackPanel Margin="12,0,0,0">
                <CheckBox Name="ChkSeparationLines" IsChecked="True"
                          Content="Create space separation lines around every room"/>
                <CheckBox Name="ChkClearExisting" Foreground="{RED}"
                          Content="Clear all existing spaces and lines first"/>
              </StackPanel>

            </StackPanel>
          </TabItem>

          <!-- ================= MANUAL ================= -->
          <TabItem Name="TabManual">
            <TabItem.Header>
              <StackPanel Orientation="Horizontal">
                <!-- Glyph: a picker crosshair, matching what the tab does. -->
                <Grid Width="15" Height="15" VerticalAlignment="Center" Margin="0,0,7,0">
                  <Border Height="1.5" Width="15" Background="{ORANGE}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  <Border Width="1.5" Height="15" Background="{ORANGE}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                  <Border Width="9" Height="9" CornerRadius="4.5" BorderBrush="{ORANGE}"
                          BorderThickness="1.5" Background="{WINDOW_BG}"
                          HorizontalAlignment="Center" VerticalAlignment="Center"/>
                </Grid>
                <TextBlock Text="Manual" VerticalAlignment="Center"/>
              </StackPanel>
            </TabItem.Header>
            <StackPanel Margin="16,14,16,14">

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
                <TextBlock Text="READ ROOMS FROM" Foreground="{TEXT_MUTED}" FontSize="11"
                           FontWeight="Bold" VerticalAlignment="Center"/>
              </StackPanel>
              <ComboBox Name="RoomSourceCombo" Height="26" Margin="12,0,0,6"
                        Background="{FIELD_BG}" Foreground="Black"/>
              <StackPanel Orientation="Horizontal" Margin="0,4,0,4">
                <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
                <TextBlock Text="ROOMS ON" Foreground="{TEXT_MUTED}" FontSize="11"
                           FontWeight="Bold" VerticalAlignment="Center"/>
              </StackPanel>
              <ComboBox Name="LevelCombo" Height="26" Margin="12,0,0,14"
                        Background="{FIELD_BG}" Foreground="Black"/>

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
                <TextBlock Text="ROOMS PICKED" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                           VerticalAlignment="Center"/>
              </StackPanel>
              <ListBox Name="RoomList" Height="132" Margin="12,0,0,6" Background="{FIELD_BG}"
                       Foreground="{TEXT}" BorderBrush="{BORDER}" SelectionMode="Extended"/>
              <StackPanel Orientation="Horizontal" Margin="12,0,0,4">
                <Button Name="PickButton" Content="Select Rooms" Width="112" Height="28"
                        Background="{ORANGE}" Foreground="White" BorderThickness="0" FontWeight="Bold"
                        Cursor="Hand" Margin="0,0,6,0"
                        ToolTip="Click rooms, Tab cycles stacked rooms, then press Finish on the options bar."/>
                <Button Name="BoxSelectButton" Content="Box Select" Width="98" Height="28"
                        Background="{CARD_BG}" Foreground="{ORANGE}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,6,0"
                        ToolTip="Drag a rectangle to add every room inside it."/>
                <Button Name="FromListButton" Content="From List" Width="92" Height="28"
                        Background="{CARD_BG}" Foreground="{BLUE}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,6,0"/>
                <Button Name="DiagnoseButton" Content="Diagnose" Width="82" Height="28"
                        Background="{CARD_BG}" Foreground="{TEXT_MUTED}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand"/>
              </StackPanel>
              <StackPanel Orientation="Horizontal" Margin="12,0,0,14">
                <Button Name="RemoveButton" Content="Remove Selected" Width="130" Height="26"
                        Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,6,0"/>
                <Button Name="ClearButton" Content="Clear" Width="80" Height="26"
                        Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,6,0"/>
                <Button Name="DeleteLinesButton" Content="Delete Lines Around Listed"
                        Width="180" Height="26" Background="{CARD_BG}" Foreground="{RED}"
                        BorderThickness="1" BorderBrush="{BORDER}" Cursor="Hand"
                        ToolTip="Delete the space separation lines inside every room in the list."/>
              </StackPanel>

              <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
                <Border Width="4" Height="14" Background="{ORANGE}" Margin="0,0,8,0"/>
                <TextBlock Text="BOUNDARY" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                           VerticalAlignment="Center"/>
              </StackPanel>
              <StackPanel Margin="12,0,0,0">
                <RadioButton Name="BoundaryLines" GroupName="boundary" IsChecked="True"
                             Content="Draw space separation lines around the room perimeter"/>
                <RadioButton Name="BoundaryNative" GroupName="boundary"
                             Content="Native space creation (no separation lines)"/>
              </StackPanel>

              <!-- Debug log: collapsed by default, expanded when something
                   needs explaining. Mirrors the file at
                   the log file under %APPDATA%/RevoBIM. -->
              <Border Background="{CARD_BG}" CornerRadius="4" Margin="0,14,0,0"
                      BorderBrush="{BORDER}" BorderThickness="1">
                <StackPanel>
                  <Button Name="DebugToggleButton" Height="26" Cursor="Hand"
                          Background="Transparent" BorderThickness="0"
                          Foreground="{TEXT_MUTED}" FontSize="11"
                          HorizontalContentAlignment="Left" Padding="10,0,0,0"
                          Content="+  Debug log"/>
                  <StackPanel Name="DebugPanel" Visibility="Collapsed"
                              Margin="8,0,8,8">
                    <TextBox Name="DebugText" Height="150" Background="{FIELD_BG}"
                             Foreground="{TEXT_MUTED}" BorderBrush="{BORDER}"
                             BorderThickness="1" Padding="6" FontFamily="Consolas"
                             FontSize="10.5" IsReadOnly="True" TextWrapping="NoWrap"
                             AcceptsReturn="True"
                             VerticalScrollBarVisibility="Auto"
                             HorizontalScrollBarVisibility="Auto"/>
                    <StackPanel Orientation="Horizontal" Margin="0,6,0,0">
                      <Button Name="DebugSelectButton" Content="Select all" Width="90"
                              Height="24" Background="{CARD_BG}" Foreground="{TEXT}"
                              BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                              Margin="0,0,6,0"/>
                      <Button Name="DebugClearButton" Content="Clear" Width="70"
                              Height="24" Background="{CARD_BG}" Foreground="{TEXT_MUTED}"
                              BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"/>
                      <TextBlock Name="DebugHint" Foreground="{TEXT_MUTED}" FontSize="10"
                                 VerticalAlignment="Center" Margin="10,0,0,0"
                                 Text="Select all, then Ctrl+C to copy."/>
                    </StackPanel>
                  </StackPanel>
                </StackPanel>
              </Border>

            </StackPanel>
          </TabItem>

          <!-- ================= MANAGE ================= -->
          <TabItem Name="TabManage">
            <TabItem.Header>
              <StackPanel Orientation="Horizontal">
                <!-- Glyph: three stacked bars, a list being managed. -->
                <Grid Width="15" Height="15" VerticalAlignment="Center" Margin="0,0,7,0">
                  <Border Height="2.5" VerticalAlignment="Top" Background="{GREEN}" CornerRadius="1"/>
                  <Border Height="2.5" VerticalAlignment="Center" Background="{GREEN}" CornerRadius="1"/>
                  <Border Height="2.5" VerticalAlignment="Bottom" Background="{GREEN}" CornerRadius="1"/>
                </Grid>
                <TextBlock Text="Manage" VerticalAlignment="Center"/>
              </StackPanel>
            </TabItem.Header>
            <Grid Margin="12,10,12,10">
              <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
              </Grid.RowDefinitions>

              <!-- toolbar -->
              <Grid Grid.Row="0" Margin="0,0,0,8">
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="*"/>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="Auto"/>
                  <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBox Name="ManageSearch" Height="26" Background="{FIELD_BG}" Foreground="{TEXT}"
                         BorderBrush="{BORDER}" BorderThickness="1" Padding="5,3,5,3"
                         VerticalContentAlignment="Center" Margin="0,0,8,0"/>
                <StackPanel Grid.Column="1" Orientation="Horizontal" VerticalAlignment="Center" Margin="0,0,8,0">
                  <TextBlock Text="Group by" Foreground="{TEXT_MUTED}" FontSize="11"
                             VerticalAlignment="Center" Margin="0,0,6,0"/>
                  <ComboBox Name="ManageGroupCombo" Width="110" Height="26"
                            Background="{FIELD_BG}" Foreground="Black"/>
                </StackPanel>
                <CheckBox Grid.Column="2" Name="ManageFlaggedOnly" Content="Flagged only"
                          VerticalAlignment="Center" Margin="0,0,10,0"/>
                <Button Grid.Column="3" Name="ManageRefreshButton" Content="Refresh" Width="76" Height="26"
                        Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand"/>
              </Grid>

              <!-- sortable column headers -->
              <Grid Name="ManageHeader" Grid.Row="1" Margin="0,0,0,2">
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width="120"/>
                  <ColumnDefinition Width="80"/>
                  <ColumnDefinition Width="*"/>
                  <ColumnDefinition Width="80"/>
                  <ColumnDefinition Width="80"/>
                  <ColumnDefinition Width="120"/>
                  <ColumnDefinition Width="72"/>
                  <ColumnDefinition Width="150"/>
                </Grid.ColumnDefinitions>
                <Button Grid.Column="0" Name="HdrLevel" Content="Level" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="1" Name="HdrNumber" Content="Number" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="2" Name="HdrName" Content="Name" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="3" Name="HdrBase" Content="Base mm" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="4" Name="HdrLimit" Content="Limit mm" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="5" Name="HdrUpper" Content="Upper Limit" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="6" Name="HdrHeight" Content="Height" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
                <Button Grid.Column="7" Name="HdrStatus" Content="Status" Height="24" Background="{CARD_BG}"
                        Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Cursor="Hand"
                        HorizontalContentAlignment="Left" Padding="6,0,0,0"/>
              </Grid>

              <ListBox Name="ManageList" Grid.Row="2" MinHeight="220" Background="{FIELD_BG}" Foreground="{TEXT}"
                       BorderBrush="{BORDER}" BorderThickness="1" SelectionMode="Extended"
                       HorizontalContentAlignment="Stretch"
                       ScrollViewer.HorizontalScrollBarVisibility="Disabled"/>

              <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="0,8,0,0">
                <Button Name="PushUpButton" Content="Push Spaces Up To Floor" Width="180" Height="28"
                        Background="{ORANGE}" Foreground="White" BorderThickness="0" FontWeight="Bold"
                        Cursor="Hand" Margin="0,0,6,0"
                        ToolTip="Select spaces in the model. Each is set to extend to the underside of the nearest floor above, without running into a space above it. Nothing is written until Apply."/>
                <Button Name="ManageDiscardButton" Content="Discard Pending" Width="120" Height="28"
                        Background="{CARD_BG}" Foreground="{TEXT_MUTED}" BorderThickness="1"
                        BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,6,0"/>
                <TextBlock Name="ManageSummary" Foreground="{TEXT_MUTED}" FontSize="11"
                           VerticalAlignment="Center"/>
              </StackPanel>

            </Grid>
          </TabItem>

        </TabControl>

        <!-- ================= SHARED ================= -->
        <StackPanel Grid.Row="1">
        <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
          <Border Width="4" Height="14" Background="{ORANGE}" Margin="0,0,8,0"/>
          <TextBlock Text="APPLIED TO BOTH" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                     VerticalAlignment="Center"/>
        </StackPanel>
        <StackPanel Margin="12,0,0,12">
          <CheckBox Name="ChkInheritName" IsChecked="True"
                    Content="Inherit room name to space name"/>
          <CheckBox Name="ChkPushCeiling"
                    Content="Push spaces to underside of floor above"/>
        </StackPanel>

        <StackPanel Orientation="Horizontal" Margin="0,0,0,6">
          <Border Width="4" Height="14" Background="{BLUE}" Margin="0,0,8,0"/>
          <TextBlock Text="WORKSET" Foreground="{TEXT_MUTED}" FontSize="11" FontWeight="Bold"
                     VerticalAlignment="Center"/>
          <TextBlock Text="  (type to search)" Foreground="{TEXT_MUTED}" FontSize="10"
                     VerticalAlignment="Center"/>
        </StackPanel>
        <StackPanel Margin="12,0,0,4">
          <ComboBox Name="WorksetCombo" Height="26" Background="{FIELD_BG}" Foreground="Black"
                    IsEditable="True" IsTextSearchEnabled="False" StaysOpenOnEdit="True"/>
        </StackPanel>
        </StackPanel>

      </Grid>
    </DockPanel>
   </Border>

   <!--RESIZEGRIPS-->
  </Grid>
</Window>
"""


SCROLLBAR_XAML = u"""
    <!-- ==================================================================
         Scrollbars. Retemplated rather than recoloured: a stock ScrollBar
         ignores Background and renders in the system light theme, which
         is why every scrollable panel had pale grey bars against the dark
         window. The styles carry no x:Key so they apply implicitly to
         every ScrollBar in the window, including the ones WPF creates
         inside a ListBox or ScrollViewer that are never named in a layout.
         ================================================================== -->

    <Style x:Key="RevoScrollThumb" TargetType="Thumb">
      <Setter Property="OverridesDefaultStyle" Value="True"/>
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Thumb">
            <Border Name="Bar" Background="#4A4A50" CornerRadius="4"
                    Margin="3,2,3,2"/>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bar" Property="Background" Value="#5E5E66"/>
              </Trigger>
              <Trigger Property="IsDragging" Value="True">
                <Setter TargetName="Bar" Property="Background" Value="{BLUE}"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <!-- The line and page buttons are made invisible but still present:
         removing them from the template breaks ScrollBar's own layout. -->
    <Style x:Key="RevoScrollHidden" TargetType="RepeatButton">
      <Setter Property="OverridesDefaultStyle" Value="True"/>
      <Setter Property="Focusable" Value="False"/>
      <Setter Property="IsTabStop" Value="False"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="RepeatButton">
            <Border Background="Transparent"/>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>

    <Style TargetType="ScrollBar">
      <Setter Property="Background" Value="Transparent"/>
      <Setter Property="Foreground" Value="#4A4A50"/>
      <Setter Property="Width" Value="11"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="ScrollBar">
            <Grid Background="Transparent">
              <Track Name="PART_Track" IsDirectionReversed="True">
                <Track.DecreaseRepeatButton>
                  <RepeatButton Style="{StaticResource RevoScrollHidden}"
                                Command="ScrollBar.PageUpCommand"/>
                </Track.DecreaseRepeatButton>
                <Track.Thumb>
                  <Thumb Style="{StaticResource RevoScrollThumb}"/>
                </Track.Thumb>
                <Track.IncreaseRepeatButton>
                  <RepeatButton Style="{StaticResource RevoScrollHidden}"
                                Command="ScrollBar.PageDownCommand"/>
                </Track.IncreaseRepeatButton>
              </Track>
            </Grid>
            <ControlTemplate.Triggers>
              <Trigger Property="Orientation" Value="Horizontal">
                <Setter Property="Width" Value="Auto"/>
                <Setter Property="Height" Value="11"/>
                <Setter TargetName="PART_Track" Property="IsDirectionReversed"
                        Value="False"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
"""


# Eight grips, 6px, around the edge of the window. A borderless
# AllowsTransparency window has nothing hit testable in its frame, so WPF's
# own resize border never fires however ResizeMode is set - the window is
# stuck at its start size unless it carries grips of its own. The overlay
# Grid has NO Background so everything underneath stays clickable.
RESIZE_GRIPS_XAML = u"""
      <Grid Name="ResizeGrips">
        <Thumb Name="GripLeft" Width="6" HorizontalAlignment="Left"
               VerticalAlignment="Stretch" Cursor="SizeWE" Opacity="0"
               Margin="0,6,0,6"/>
        <Thumb Name="GripRight" Width="6" HorizontalAlignment="Right"
               VerticalAlignment="Stretch" Cursor="SizeWE" Opacity="0"
               Margin="0,6,0,6"/>
        <Thumb Name="GripTop" Height="6" VerticalAlignment="Top"
               HorizontalAlignment="Stretch" Cursor="SizeNS" Opacity="0"
               Margin="6,0,6,0"/>
        <Thumb Name="GripBottom" Height="6" VerticalAlignment="Bottom"
               HorizontalAlignment="Stretch" Cursor="SizeNS" Opacity="0"
               Margin="6,0,6,0"/>
        <Thumb Name="GripTopLeft" Width="8" Height="8" HorizontalAlignment="Left"
               VerticalAlignment="Top" Cursor="SizeNWSE" Opacity="0"/>
        <Thumb Name="GripTopRight" Width="8" Height="8" HorizontalAlignment="Right"
               VerticalAlignment="Top" Cursor="SizeNESW" Opacity="0"/>
        <Thumb Name="GripBottomLeft" Width="8" Height="8" HorizontalAlignment="Left"
               VerticalAlignment="Bottom" Cursor="SizeNESW" Opacity="0"/>
        <Thumb Name="GripBottomRight" Width="8" Height="8" HorizontalAlignment="Right"
               VerticalAlignment="Bottom" Cursor="SizeNWSE" Opacity="0"/>
      </Grid>
"""


def _themed(xaml):
    xaml = xaml.replace("__VERSION__", __version__)
    # Shared blocks first, so their own palette tokens are substituted below.
    xaml = xaml.replace("<!--SCROLLBARS-->", SCROLLBAR_XAML)
    xaml = xaml.replace("<!--RESIZEGRIPS-->", RESIZE_GRIPS_XAML)
    xaml = xaml.replace("{WINDOW_BG}", theme.WINDOW_BG)
    xaml = xaml.replace("{BAR_BG}", theme.BAR_BG)
    xaml = xaml.replace("{CARD_BG}", theme.CARD_BG)
    xaml = xaml.replace("{FIELD_BG}", theme.FIELD_BG)
    xaml = xaml.replace("{BORDER}", theme.BORDER)
    xaml = xaml.replace("{TEXT_MUTED}", theme.TEXT_MUTED)
    xaml = xaml.replace("{TEXT}", theme.TEXT)
    xaml = xaml.replace("{BLUE}", theme.BLUE)
    xaml = xaml.replace("{ORANGE}", theme.ORANGE)
    xaml = xaml.replace("{GREEN}", theme.GREEN)
    xaml = xaml.replace("{RED}", theme.RED)
    return xaml


def wire_resize_grips(window):
    """Makes a borderless window resizable.

    WPF gives an `AllowsTransparency` window no hit-testable frame, so its
    own resize border never fires however ResizeMode is set and the window
    is stuck at its start size. Eight Thumbs around the edge do the job
    instead. The overlay Grid has no Background, so everything under it
    stays clickable.

    Each drag moves Left/Top as well as Width/Height where the edge being
    pulled is the left or top one, and every change is clamped at
    MinWidth/MinHeight - without the clamp a fast drag inverts the window."""
    find = window.FindName

    def resize(horizontal, vertical):
        """horizontal/vertical: -1 pulls the left/top edge, +1 the
        right/bottom edge, 0 leaves that axis alone."""
        def handler(sender, args):
            try:
                dx = args.HorizontalChange
                dy = args.VerticalChange

                if horizontal < 0:
                    width = window.Width - dx
                    if width >= window.MinWidth:
                        window.Left = window.Left + dx
                        window.Width = width
                elif horizontal > 0:
                    width = window.Width + dx
                    if width >= window.MinWidth:
                        window.Width = width

                if vertical < 0:
                    height = window.Height - dy
                    if height >= window.MinHeight:
                        window.Top = window.Top + dy
                        window.Height = height
                elif vertical > 0:
                    height = window.Height + dy
                    if height >= window.MinHeight:
                        window.Height = height
            except Exception:
                pass
        return handler

    grips = [
        ("GripLeft", -1, 0), ("GripRight", 1, 0),
        ("GripTop", 0, -1), ("GripBottom", 0, 1),
        ("GripTopLeft", -1, -1), ("GripTopRight", 1, -1),
        ("GripBottomLeft", -1, 1), ("GripBottomRight", 1, 1),
    ]
    for name, horizontal, vertical in grips:
        thumb = find(name)
        if thumb is not None:
            thumb.DragDelta += resize(horizontal, vertical)


def build_window():
    # XamlReader.Parse takes the string directly - no System.Xml dependency.
    return XamlReader.Parse(_themed(XAML))


# ---------------------------------------------------------------------------
# Workset dropdown with live keyword search
# ---------------------------------------------------------------------------

REPORT_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM Space Creator - diagnosis"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        SizeToContent="Height" Width="600" ShowInTaskbar="True">

  <Window.Resources>
    <!--SCROLLBARS-->
  </Window.Resources>

  <Border CornerRadius="6" Background="{WINDOW_BG}" BorderBrush="#4A4A50" BorderThickness="1">
    <DockPanel LastChildFill="True">

      <Border DockPanel.Dock="Top" Background="{BAR_BG}" CornerRadius="6,6,0,0" Height="52"
              Name="ReportHeaderBar">
        <Grid Margin="14,0,10,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <StackPanel Orientation="Vertical" VerticalAlignment="Center">
            <TextBlock Text="RevoBIM" FontSize="20" FontWeight="Bold" Foreground="{BLUE}"/>
            <TextBlock Text="What the tool can see" FontSize="13" Foreground="{ORANGE}"
                       Margin="0,-2,0,0"/>
          </StackPanel>
          <Button Grid.Column="1" Name="ReportCloseButton" Content="&#x2715;" Width="26" Height="26"
                  Background="Transparent" BorderThickness="0" Foreground="{TEXT_MUTED}" FontSize="13"
                  Cursor="Hand"/>
        </Grid>
      </Border>

      <Border DockPanel.Dock="Bottom" Background="{BAR_BG}" CornerRadius="0,0,6,6" Height="48">
        <Grid Margin="14,0,14,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <TextBlock Name="ReportHint" Foreground="{TEXT_MUTED}" FontSize="11"
                     VerticalAlignment="Center"
                     Text="Select the text to copy it."/>
          <Button Grid.Column="1" Name="ReportOkButton" Content="Close" Width="90" Height="30"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                  BorderBrush="{BORDER}" Cursor="Hand"/>
        </Grid>
      </Border>

      <ScrollViewer Margin="16,14,16,10" Height="420" VerticalScrollBarVisibility="Auto"
                    HorizontalScrollBarVisibility="Auto">
        <TextBox Name="ReportText" Background="{FIELD_BG}" Foreground="{TEXT}"
                 BorderBrush="{BORDER}" BorderThickness="1" Padding="8"
                 FontFamily="Consolas" FontSize="11.5"
                 IsReadOnly="True" TextWrapping="NoWrap"
                 AcceptsReturn="True" VerticalScrollBarVisibility="Disabled"/>
      </ScrollViewer>
    </DockPanel>
  </Border>
</Window>
"""


def show_report_window(lines):
    """A read-only, selectable report. Read-only rather than a TextBlock so
    it can be selected and pasted somewhere."""
    window = XamlReader.Parse(_themed(REPORT_XAML))
    find = window.FindName
    find("ReportText").Text = "\n".join(lines)

    def on_close(sender, args):
        window.Close()
    find("ReportCloseButton").Click += on_close
    find("ReportOkButton").Click += on_close

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    find("ReportHeaderBar").MouseLeftButtonDown += on_drag

    try:
        helper = WindowInteropHelper(window)
        helper.Owner = revit.uiapp.MainWindowHandle
    except Exception:
        pass

    window.ShowDialog()


ROOMLIST_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM Space Creator - add rooms from list"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        SizeToContent="Height" Width="560" ShowInTaskbar="True">

  <Window.Resources>
    <!--SCROLLBARS-->
  </Window.Resources>

  <Border CornerRadius="6" Background="{WINDOW_BG}" BorderBrush="#4A4A50" BorderThickness="1">
    <DockPanel LastChildFill="True">

      <Border DockPanel.Dock="Top" Background="{BAR_BG}" CornerRadius="6,6,0,0" Height="52"
              Name="RoomListHeaderBar">
        <Grid Margin="14,0,10,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <StackPanel Orientation="Vertical" VerticalAlignment="Center">
            <TextBlock Text="RevoBIM" FontSize="20" FontWeight="Bold" Foreground="{BLUE}"/>
            <TextBlock Text="Add rooms from list" FontSize="13" Foreground="{ORANGE}"
                       Margin="0,-2,0,0"/>
          </StackPanel>
          <Button Grid.Column="1" Name="RoomListCloseButton" Content="&#x2715;" Width="26" Height="26"
                  Background="Transparent" BorderThickness="0" Foreground="{TEXT_MUTED}" FontSize="13"
                  Cursor="Hand"/>
        </Grid>
      </Border>

      <Border DockPanel.Dock="Bottom" Background="{BAR_BG}" CornerRadius="0,0,6,6" Height="52">
        <Grid Margin="14,0,14,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <TextBlock Name="RoomListStatus" Text="" Foreground="{TEXT_MUTED}" FontSize="11"
                     VerticalAlignment="Center"/>
          <Button Grid.Column="1" Name="RoomListCancelButton" Content="Cancel" Width="90" Height="30"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                  BorderBrush="{BORDER}" Cursor="Hand" Margin="0,0,8,0"/>
          <Button Grid.Column="2" Name="RoomListAddButton" Content="Add Selected" Width="130" Height="30"
                  Background="{GREEN}" Foreground="White" BorderThickness="0" FontWeight="Bold"
                  Cursor="Hand"/>
        </Grid>
      </Border>

      <StackPanel Margin="16,14,16,10">
        <TextBlock Text="Every room in the selected source. Ctrl-click or shift-click for several."
                   Foreground="{TEXT_MUTED}" FontSize="11" Margin="0,0,0,8" TextWrapping="Wrap"/>
        <TextBox Name="RoomListSearch" Height="26" Margin="0,0,0,8" Background="{FIELD_BG}"
                 Foreground="{TEXT}" BorderBrush="{BORDER}" BorderThickness="1" Padding="5,3,5,3"/>
        <ListBox Name="RoomListBox" Height="330" Background="{FIELD_BG}" Foreground="{TEXT}"
                 BorderBrush="{BORDER}" BorderThickness="1" SelectionMode="Extended"/>
      </StackPanel>
    </DockPanel>
  </Border>
</Window>
"""


def show_room_list_window(on_add, status_text, source_key='all'):
    """Adds linked rooms by choosing them from a list.

    This exists because picking can be defeated by things that have
    nothing to do with the tool - a view template locking visibility, the
    link's display settings, phasing, or simply being in a view type where
    PickPoint is not offered. Reading the rooms out of the link works
    regardless, so there is always a route that does not depend on a click
    landing."""
    entries = core.list_all_linked_rooms(doc)
    if source_key != "all":
        sources = core.filter_sources(core.get_room_sources(doc), source_key)
        wanted = set()
        for source in sources:
            wanted.add(source["label"])
        entries = [e for e in entries if e["link_title"] in wanted]
    if not entries:
        status_text.Text = "No rooms found in the selected source."
        return

    window = XamlReader.Parse(_themed(ROOMLIST_XAML))
    find = window.FindName
    list_box = find("RoomListBox")
    search_box = find("RoomListSearch")
    visible = []

    def label(entry):
        parts = [entry["link_title"], entry["level"]]
        room_part = entry["number"]
        if entry["name"]:
            room_part = (room_part + " - " + entry["name"]) if room_part else entry["name"]
        parts.append(room_part or "(unnamed)")
        return "   |   ".join([p for p in parts if p])

    def refresh(needle):
        needle = (needle or "").strip().lower()
        del visible[:]
        list_box.Items.Clear()
        for entry in entries:
            text = label(entry)
            if not needle or needle in text.lower():
                visible.append(entry)
                list_box.Items.Add(text)
        find("RoomListStatus").Text = str(len(visible)) + " of " + \
            str(len(entries)) + " room(s) shown"

    def on_search(sender, args):
        refresh(search_box.Text)
    search_box.TextChanged += on_search

    def on_add_click(sender, args):
        chosen = []
        for item in list_box.SelectedItems:
            index = list_box.Items.IndexOf(item)
            if 0 <= index < len(visible):
                chosen.append(visible[index])
        window.Close()
        if chosen:
            on_add(chosen)

    find("RoomListAddButton").Click += on_add_click

    def on_close(sender, args):
        window.Close()
    find("RoomListCloseButton").Click += on_close
    find("RoomListCancelButton").Click += on_close

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    find("RoomListHeaderBar").MouseLeftButtonDown += on_drag

    refresh("")

    try:
        helper = WindowInteropHelper(window)
        helper.Owner = revit.uiapp.MainWindowHandle
    except Exception:
        pass

    window.ShowDialog()


RESULTS_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM Space Creator - spaces created"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        SizeToContent="Height" Width="560" ShowInTaskbar="True">

  <Window.Resources>
    <!--SCROLLBARS-->
  </Window.Resources>

  <Border CornerRadius="6" Background="{WINDOW_BG}" BorderBrush="#4A4A50" BorderThickness="1">
    <DockPanel LastChildFill="True">

      <Border DockPanel.Dock="Top" Background="{BAR_BG}" CornerRadius="6,6,0,0" Height="52"
              Name="ResultsHeaderBar">
        <Grid Margin="14,0,10,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <StackPanel Orientation="Vertical" VerticalAlignment="Center">
            <TextBlock Text="RevoBIM" FontSize="20" FontWeight="Bold" Foreground="{BLUE}"/>
            <TextBlock Text="Spaces created" FontSize="13" Foreground="{ORANGE}" Margin="0,-2,0,0"/>
          </StackPanel>
          <Button Grid.Column="1" Name="ResultsCloseButton" Content="&#x2715;" Width="26" Height="26"
                  Background="Transparent" BorderThickness="0" Foreground="{TEXT_MUTED}" FontSize="13"
                  Cursor="Hand"/>
        </Grid>
      </Border>

      <Border DockPanel.Dock="Bottom" Background="{BAR_BG}" CornerRadius="0,0,6,6" Height="48">
        <Grid Margin="14,0,14,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <TextBlock Name="ResultsCount" Text="" Foreground="{TEXT_MUTED}" FontSize="11"
                     VerticalAlignment="Center"/>
          <Button Grid.Column="1" Name="ResultsOkButton" Content="Close" Width="90" Height="30"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                  BorderBrush="{BORDER}" Cursor="Hand"/>
        </Grid>
      </Border>

      <StackPanel Margin="16,14,16,10">

        <TextBlock Name="ResultsIntro" Text="" Foreground="{TEXT}" FontSize="12"
                   TextWrapping="Wrap" Margin="0,0,0,10"/>

        <!-- Sortable column headers -->
        <Grid Margin="0,0,0,2">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="170" />
            <ColumnDefinition Width="90" />
            <ColumnDefinition Width="*" />
          </Grid.ColumnDefinitions>
          <Button Grid.Column="0" Name="SortLevelButton" Content="Level" Height="26"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderBrush="{BORDER}"
                  BorderThickness="1" Cursor="Hand" HorizontalContentAlignment="Left"
                  Padding="8,0,0,0"/>
          <Button Grid.Column="1" Name="SortNumberButton" Content="Number" Height="26"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderBrush="{BORDER}"
                  BorderThickness="1" Cursor="Hand" HorizontalContentAlignment="Left"
                  Padding="8,0,0,0"/>
          <Button Grid.Column="2" Name="SortNameButton" Content="Name" Height="26"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderBrush="{BORDER}"
                  BorderThickness="1" Cursor="Hand" HorizontalContentAlignment="Left"
                  Padding="8,0,0,0"/>
        </Grid>

        <ListBox Name="ResultsList" Height="300" Background="{FIELD_BG}" Foreground="{TEXT}"
                 BorderBrush="{BORDER}" BorderThickness="1"
                 HorizontalContentAlignment="Stretch"/>

      </StackPanel>
    </DockPanel>
  </Border>
</Window>
"""


def show_results_window(rows, skipped_count):
    """A themed, sortable list of the spaces just created.

    Rows are built as WPF elements in code rather than bound to Python
    objects - binding to IronPython objects is unreliable across engine
    versions, and this sidesteps the question entirely. Sorting rebuilds
    the row list rather than going through a CollectionView."""
    if not rows:
        return

    window = XamlReader.Parse(_themed(RESULTS_XAML))
    find = window.FindName

    list_box = find("ResultsList")
    state = {"key": 0, "descending": False}

    def build_row(row):
        grid = Grid()
        for width in (170, 90, 0):
            column = ColumnDefinition()
            if width:
                column.Width = GridLength(width)
            else:
                column.Width = GridLength(1, GridUnitType.Star)
            grid.ColumnDefinitions.Add(column)

        for index, text in enumerate(row):
            block = TextBlock()
            block.Text = text or ""
            block.Foreground = _brush(theme.TEXT if index == 2 else theme.TEXT_MUTED)
            block.Margin = Thickness(8, 2, 6, 2)
            block.TextTrimming = TextTrimming.CharacterEllipsis
            Grid.SetColumn(block, index)
            grid.Children.Add(block)
        return grid

    def refresh():
        ordered = sorted(
            rows,
            key=lambda r: ((r[state["key"]] or "").lower(), (r[0] or "").lower()),
            reverse=state["descending"])
        list_box.Items.Clear()
        for row in ordered:
            list_box.Items.Add(build_row(row))

        labels = ["Level", "Number", "Name"]
        arrow = " v" if state["descending"] else " ^"
        find("SortLevelButton").Content = labels[0] + (arrow if state["key"] == 0 else "")
        find("SortNumberButton").Content = labels[1] + (arrow if state["key"] == 1 else "")
        find("SortNameButton").Content = labels[2] + (arrow if state["key"] == 2 else "")

    def sort_by(key):
        def handler(sender, args):
            if state["key"] == key:
                state["descending"] = not state["descending"]
            else:
                state["key"] = key
                state["descending"] = False
            refresh()
        return handler

    find("SortLevelButton").Click += sort_by(0)
    find("SortNumberButton").Click += sort_by(1)
    find("SortNameButton").Click += sort_by(2)

    intro = str(len(rows)) + " space(s) created."
    if skipped_count:
        intro += " " + str(skipped_count) + \
                 " room(s) already had a space and were left alone."
    find("ResultsIntro").Text = intro
    find("ResultsCount").Text = "Click a column heading to sort."

    def on_close(sender, args):
        window.Close()
    find("ResultsCloseButton").Click += on_close
    find("ResultsOkButton").Click += on_close

    header = find("ResultsHeaderBar")

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    header.MouseLeftButtonDown += on_drag

    refresh()

    try:
        helper = WindowInteropHelper(window)
        helper.Owner = revit.uiapp.MainWindowHandle
    except Exception:
        pass

    window.Show()



def wire_workset_combo(combo, worksets):
    """An editable ComboBox that filters as you type.

    The search lives in the dropdown itself rather than in a separate box:
    typing narrows the list and opens it. IsTextSearchEnabled is off
    because WPF's built-in prefix jump fights with the filtering, and the
    text is matched back to a workset by name on read - SelectedItem is
    null whenever the user has typed something that is not an exact item."""
    all_names = [name for name, _wsid in worksets]
    state = {"filtering": False}

    def rebuild(filter_text):
        combo.Items.Clear()
        combo.Items.Add(NONE_WORKSET)
        needle = (filter_text or "").strip().lower()
        for name in all_names:
            if not needle or needle in name.lower():
                combo.Items.Add(name)

    def on_key_up(sender, args):
        if state["filtering"]:
            return
        state["filtering"] = True
        try:
            typed = combo.Text
            rebuild(typed)
            combo.Text = typed
            try:
                editable = combo.Template.FindName("PART_EditableTextBox", combo)
                if editable is not None:
                    editable.CaretIndex = len(typed or "")
            except Exception:
                pass
            combo.IsDropDownOpen = True
        finally:
            state["filtering"] = False

    combo.KeyUp += on_key_up
    rebuild("")
    combo.Text = NONE_WORKSET

    def resolve_selected_workset():
        chosen = None
        try:
            chosen = combo.SelectedItem
        except Exception:
            chosen = None
        if chosen is None:
            try:
                chosen = combo.Text
            except Exception:
                return None
        if not chosen or chosen == NONE_WORKSET:
            return None
        for name, wsid in worksets:
            if name == chosen:
                return wsid
        return None

    return resolve_selected_workset


# ---------------------------------------------------------------------------
# Picked-room bookkeeping
# ---------------------------------------------------------------------------

class PickedRoom(object):
    def __init__(self, link_instance_id, link_doc_title, room_id, room_name,
                 room_number, level_name=""):
        self.link_instance_id = link_instance_id
        self.link_doc_title = link_doc_title
        self.room_id = room_id
        self.room_name = room_name
        self.room_number = room_number
        # The level is shown in the list because a room from the wrong
        # storey is otherwise indistinguishable from the right one.
        self.level_name = level_name
        # Nothing is drawn until Create Spaces, so these stay empty until
        # then. They are kept so a future change that draws earlier can
        # still clean up after itself.
        self.line_ids = []
        self.lines_drawn = 0

    def key(self):
        return (core.eid_value(self.link_instance_id), core.eid_value(self.room_id))

    def display(self):
        label = self.room_name or "(unnamed)"
        if self.room_number:
            label = self.room_number + " - " + label
        text = label
        if self.level_name:
            text += "   (" + self.level_name + ")"
        text += "   -  " + self.link_doc_title
        return text


# ---------------------------------------------------------------------------
# Reading the window
# ---------------------------------------------------------------------------

class Progress(object):
    """Drives the progress band.

    Two hard rules from elsewhere in this extension are respected:

    - **The dispatcher is never pumped inside an open transaction.** Doing
      so can leave the write with nothing committed, which is how Fire
      Damper Wall Type Push came to report success and write nothing.
      pump() is only ever called between chunks, with no transaction open.
    - **Pumping also pumps input**, so the window is made hit-test
      invisible for the duration and put back afterwards. Otherwise a
      click mid-run can tear a handler away from work in progress.

    It also only repaints when the whole percent moves - pumping on every
    one of several hundred rooms costs more than the work being measured.
    """

    def __init__(self, window):
        self.window = window
        self.panel = window.FindName("ProgressPanel")
        self.bar = window.FindName("RunProgressBar")
        self.text = window.FindName("ProgressText")
        self.total = 0
        self.done = 0
        self.last_percent = -1
        self.label = ""

    def start(self, total, label):
        self.total = max(0, total)
        self.done = 0
        self.last_percent = -1
        self.label = label
        try:
            self.window.IsHitTestVisible = False
            self.panel.Visibility = Visibility.Visible
            self.bar.Value = 0
            self.text.Text = label
        except Exception:
            pass
        self.pump()

    def advance(self, count=1):
        self.done += count
        if self.total <= 0:
            return
        percent = int((self.done * 100) / self.total)
        if percent == self.last_percent:
            return
        self.last_percent = percent
        try:
            self.bar.Value = percent
            self.text.Text = self.label + "  " + str(self.done) + " / " + \
                str(self.total) + "  (" + str(percent) + "%)"
        except Exception:
            pass
        self.pump()

    def finish(self):
        try:
            self.panel.Visibility = Visibility.Collapsed
            self.window.IsHitTestVisible = True
        except Exception:
            pass
        self.pump()

    def pump(self):
        """Lets WPF repaint. MUST NOT be called with a transaction open."""
        try:
            self.window.Dispatcher.Invoke(Action(lambda: None),
                                          DispatcherPriority.Background)
        except Exception:
            pass


def combo_text_of(window):
    """The workset combo's current text. It is editable, so SelectedItem
    is null whenever the user has typed rather than picked."""
    combo = window.FindName("WorksetCombo")
    try:
        chosen = combo.SelectedItem
    except Exception:
        chosen = None
    if chosen:
        return chosen
    try:
        return combo.Text
    except Exception:
        return ""


class ManageGrid(object):
    """The space management grid.

    Rows are built as WPF elements in code and the model is a plain list of
    dicts - nothing is bound to a Python object, per the house rule.
    Sorting, grouping and filtering all rebuild the ListBox from the dict
    list. The two offset cells are TextBoxes; editing one records a
    pending value on the row, turns it orange, and nothing touches the
    model until Apply."""

    COLUMNS = [
        ("level", 120), ("number", 80), ("name", 0), ("base", 80),
        ("limit", 80), ("upper", 120), ("height", 72), ("status", 150),
    ]
    SORT_KEYS = {
        "level": lambda r: (r["level_elev"], core_natural(r["number"])),
        "number": lambda r: core_natural(r["number"]),
        "name": lambda r: (r["name"] or "").lower(),
        "base": lambda r: r["pending_base"] if r["pending_base"] is not None
                          else r["base_offset"],
        "limit": lambda r: r["pending_limit"] if r["pending_limit"] is not None
                           else r["limit_offset"],
        "upper": lambda r: ((r["upper_level_elev"] or 0.0), (r["upper_level"] or "")),
        "height": lambda r: r["height"],
        "status": lambda r: (r["flag"] or r["status"] or ""),
    }
    GROUPS = ["None", "Level", "Upper Limit", "Status"]

    def __init__(self, window, status_text):
        find = window.FindName
        self.list_box = find("ManageList")
        self.search = find("ManageSearch")
        self.group_combo = find("ManageGroupCombo")
        self.flagged_only = find("ManageFlaggedOnly")
        self.summary = find("ManageSummary")
        self.status_text = status_text
        self.rows = []
        self.sort_key = "level"
        self.descending = False
        self.rebuilding = False
        self.headers = {
            "level": find("HdrLevel"), "number": find("HdrNumber"),
            "name": find("HdrName"), "base": find("HdrBase"),
            "limit": find("HdrLimit"), "upper": find("HdrUpper"),
            "height": find("HdrHeight"), "status": find("HdrStatus"),
        }
        for key, button in self.headers.items():
            button.Click += self._sorter(key)

        for label in self.GROUPS:
            self.group_combo.Items.Add(label)
        self.group_combo.SelectedIndex = 0
        self.group_combo.SelectionChanged += lambda s, a: self.refresh()
        self.search.TextChanged += lambda s, a: self.refresh()
        self.flagged_only.Click += lambda s, a: self.refresh()

    # --- data ----------------------------------------------------------

    def load(self):
        self.rows = core.all_space_rows(doc)
        core.log_pick("manage: loaded " + str(len(self.rows)) + " space(s)")
        self.refresh()

    def pending_rows(self):
        return [r for r in self.rows
                if r["pending_base"] is not None or
                r["pending_limit"] is not None or
                r["pending_upper_id"] is not None]

    def flagged_rows(self):
        return [r for r in self.rows if r["flag"]]

    def discard(self):
        for row in self.rows:
            row["pending_base"] = None
            row["pending_limit"] = None
            row["pending_upper_id"] = None
            row["pending_upper"] = ""
            row["status"] = ""
            row["flag"] = ""
        self.refresh()

    def row_by_id(self, id_value):
        for row in self.rows:
            if row["id_value"] == id_value:
                return row
        return None

    # --- presentation --------------------------------------------------

    def _sorter(self, key):
        def handler(sender, args):
            if self.sort_key == key:
                self.descending = not self.descending
            else:
                self.sort_key = key
                self.descending = False
            self.refresh()
        return handler

    def _visible_rows(self):
        needle = ""
        try:
            needle = (self.search.Text or "").strip().lower()
        except Exception:
            pass
        only_flagged = False
        try:
            only_flagged = bool(self.flagged_only.IsChecked)
        except Exception:
            pass

        rows = []
        for row in self.rows:
            if only_flagged and not row["flag"]:
                continue
            if needle:
                haystack = " ".join([row["level"], row["number"], row["name"],
                                     row["upper_level"], row["status"],
                                     row["flag"]]).lower()
                if needle not in haystack:
                    continue
            rows.append(row)

        key_fn = self.SORT_KEYS.get(self.sort_key, self.SORT_KEYS["level"])
        rows.sort(key=key_fn, reverse=self.descending)
        return rows

    def _group_of(self, row):
        try:
            mode = self.GROUPS[self.group_combo.SelectedIndex]
        except Exception:
            mode = "None"
        if mode == "Level":
            return (row["level_elev"], row["level"] or "(no level)")
        if mode == "Upper Limit":
            return ((row["upper_level_elev"] or 0.0),
                    row["upper_level"] or "(none)")
        if mode == "Status":
            label = "Flagged" if row["flag"] else (
                "Pending" if self._is_pending(row) else "Unchanged")
            return ({"Flagged": 0, "Pending": 1, "Unchanged": 2}[label], label)
        return None

    def _is_pending(self, row):
        return (row["pending_base"] is not None or
                row["pending_limit"] is not None or
                row["pending_upper_id"] is not None)

    def refresh(self):
        self.rebuilding = True
        try:
            self.list_box.Items.Clear()
            rows = self._visible_rows()

            grouping = self._group_of(rows[0]) is not None if rows else False
            if grouping:
                # Groups keep the sort order of their first member rather
                # than being alphabetised, so a level-sorted list stays in
                # building order when grouped by level.
                order = []
                buckets = {}
                for row in rows:
                    group = self._group_of(row)
                    if group not in buckets:
                        buckets[group] = []
                        order.append(group)
                    buckets[group].append(row)
                for group in order:
                    self.list_box.Items.Add(self._group_header(group[1],
                                                               len(buckets[group])))
                    for row in buckets[group]:
                        self.list_box.Items.Add(self._row_element(row))
            else:
                for row in rows:
                    self.list_box.Items.Add(self._row_element(row))

            for key, button in self.headers.items():
                label = {"level": "Level", "number": "Number", "name": "Name",
                         "base": "Base mm", "limit": "Limit mm",
                         "upper": "Upper Limit", "height": "Height",
                         "status": "Status"}[key]
                if key == self.sort_key:
                    label += " v" if self.descending else " ^"
                button.Content = label

            pending = len(self.pending_rows())
            flagged = len(self.flagged_rows())
            text = str(len(rows)) + " of " + str(len(self.rows)) + " space(s)"
            if pending:
                text += "  |  " + str(pending) + " pending"
            if flagged:
                text += "  |  " + str(flagged) + " flagged"
            self.summary.Text = text
        finally:
            self.rebuilding = False

    def _group_header(self, label, count):
        border = Border()
        border.Background = _brush(theme.CARD_BG)
        border.Padding = Thickness(8, 3, 8, 3)
        block = TextBlock()
        block.Text = str(label) + "   (" + str(count) + ")"
        block.Foreground = _brush(theme.BLUE)
        block.FontWeight = FontWeights.Bold
        border.Child = block
        item = ListBoxItem()
        item.Content = border
        item.IsEnabled = False
        return item

    def _row_element(self, row):
        grid = Grid()
        for _key, width in self.COLUMNS:
            column = ColumnDefinition()
            column.Width = GridLength(width) if width else \
                GridLength(1, GridUnitType.Star)
            grid.ColumnDefinitions.Add(column)

        pending = self._is_pending(row)
        colour = theme.RED if row["flag"] else (
            theme.ORANGE if pending else theme.TEXT)

        def text_cell(index, text, fg=None):
            block = TextBlock()
            block.Text = text or ""
            block.Foreground = _brush(fg or colour)
            block.Margin = Thickness(6, 3, 4, 3)
            block.VerticalAlignment = VerticalAlignment.Center
            block.TextTrimming = TextTrimming.CharacterEllipsis
            Grid.SetColumn(block, index)
            grid.Children.Add(block)

        def edit_cell(index, value, field):
            box = TextBox()
            box.Text = str(value)
            box.Margin = Thickness(4, 1, 4, 1)
            box.Padding = Thickness(3, 1, 3, 1)
            box.Background = _brush(theme.FIELD_BG)
            box.Foreground = _brush(theme.ORANGE if row[field] is not None
                                    else theme.TEXT)
            box.BorderBrush = _brush(theme.BORDER)
            box.VerticalContentAlignment = VerticalAlignment.Center
            box.Tag = (row["id_value"], field)

            def on_lost_focus(sender, args):
                if self.rebuilding:
                    return
                self._commit_edit(sender)
            box.LostFocus += on_lost_focus
            Grid.SetColumn(box, index)
            grid.Children.Add(box)

        text_cell(0, row["level"])
        text_cell(1, row["number"])
        text_cell(2, row["name"])

        base_shown = row["pending_base"] if row["pending_base"] is not None \
            else row["base_offset"]
        limit_shown = row["pending_limit"] if row["pending_limit"] is not None \
            else row["limit_offset"]
        edit_cell(3, base_shown, "pending_base")
        edit_cell(4, limit_shown, "pending_limit")

        upper = row["pending_upper"] or row["upper_level"]
        text_cell(5, upper, theme.ORANGE if row["pending_upper_id"] is not None
                  else colour)
        text_cell(6, str(row["height"]))
        text_cell(7, row["flag"] or row["status"],
                  theme.RED if row["flag"] else (
                      theme.ORANGE if pending else theme.TEXT_MUTED))

        item = ListBoxItem()
        item.Content = grid
        item.Tag = row["id_value"]
        return item

    def _commit_edit(self, box):
        try:
            id_value, field = box.Tag
        except Exception:
            return
        row = self.row_by_id(id_value)
        if row is None:
            return
        text = (box.Text or "").strip()
        original = row["base_offset"] if field == "pending_base" else row["limit_offset"]
        if text == "":
            row[field] = None
        else:
            try:
                value = int(round(float(text)))
            except Exception:
                box.Text = str(row[field] if row[field] is not None else original)
                self.status_text.Text = "'" + text + "' is not a number of millimetres."
                return
            row[field] = None if value == original else value
        if self._is_pending(row):
            if not row["flag"]:
                row["status"] = "pending"
        else:
            row["status"] = ""
        self.refresh()


def core_natural(text):
    try:
        return core._natural_key(text)
    except Exception:
        return [(0, 0, str(text or "").lower())]


class Options(object):
    """A snapshot of the window, taken on the UI thread before an external
    event is raised - the handler must not reach back into WPF."""

    def __init__(self, window, resolve_selected_workset):
        find = window.FindName
        self.scope = "current_view" if find("ScopeCurrentView").IsChecked else "all_project"
        if find("SourceHost").IsChecked:
            self.room_source = "host"
        elif find("SourceLinks").IsChecked:
            self.room_source = "links"
        else:
            self.room_source = "both"
        self.make_lines = bool(find("ChkSeparationLines").IsChecked)
        self.clear_existing = bool(find("ChkClearExisting").IsChecked)
        self.boundary_mode = "native" if find("BoundaryNative").IsChecked else "lines"
        self.inherit_name = bool(find("ChkInheritName").IsChecked)
        self.push_ceiling = bool(find("ChkPushCeiling").IsChecked)
        self.workset_id = resolve_selected_workset()
        self.workset_name = ""
        try:
            chosen = combo_text_of(window)
            if chosen and chosen != NONE_WORKSET:
                self.workset_name = chosen
        except Exception:
            self.workset_name = ""

    def save(self):
        settings = core.load_settings()
        settings["scope"] = self.scope
        settings["room_source"] = self.room_source
        settings["create_separation_lines"] = "1" if self.make_lines else "0"
        settings["clear_existing"] = "1" if self.clear_existing else "0"
        settings["boundary_mode"] = self.boundary_mode
        settings["inherit_room_name"] = "1" if self.inherit_name else "0"
        settings["push_to_ceiling"] = "1" if self.push_ceiling else "0"
        settings["workset_name"] = self.workset_name
        core.save_settings(settings)


# ---------------------------------------------------------------------------
# External event handler - picking linked rooms
# ---------------------------------------------------------------------------

class PickRoomHandler(IExternalEventHandler):
    """Selects rooms in the view by rectangle or by click.

    Uses PickBox rather than PickObject. **A room is not a pickable
    element in Revit** - not in a link, not in this model - so no amount
    of clicking one will ever select it, which is what made every earlier
    attempt at this look dead. A rectangle is just a pair of coordinates,
    and which rooms fall inside it can be worked out directly, so
    pickability never comes into it.

    A drag selects every room whose location point is inside the
    rectangle. A click - a rectangle too small to be a real drag - falls
    back to point-in-room, so single rooms still work the obvious way.
    The loop repeats until Escape, so several boxes can be dragged in one
    session."""

    def __init__(self, window, list_box, status_text):
        self.window = window
        self.list_box = list_box
        self.status_text = status_text
        # Both set on the UI thread before Raise() - the handler never
        # reads WPF.
        self.source_key = "all"
        # "pick" clicks rooms one at a time with Tab cycling and Revit's
        # own highlighting; "box" drags a rectangle.
        self.mode = "pick"
        # (low, high) host elevations, or None for every level. Only the
        # box mode uses it - a clicked room is the room the user pointed
        # at, so no level filtering is wanted or applied.
        self.band = None
        self.band_label = ""

    def Execute(self, uiapp):
        ui_document = uiapp.ActiveUIDocument

        # The window is NOT hidden while picking. Revit cannot highlight a
        # linked room - a room is not a pickable element - so the list
        # filling in as each room is clicked is the only feedback there
        # is, and hiding the window took even that away. It is modeless,
        # so Revit stays fully usable underneath; drag it aside if it is
        # over the area being picked.
        active_view = doc.ActiveView

        restore_cats = []
        restore_links = []
        vis_error = None
        try:
            tvis = Transaction(doc, "RevoBIM - show rooms for picking")
            tvis.Start()
            restore_cats, cat_error = core.show_room_categories(doc, active_view)
            restore_links, link_error = core.force_links_by_host_view(doc, active_view)
            vis_error = cat_error or link_error
            tvis.Commit()
        except Exception as ex:
            vis_error = str(ex)

        all_sources = core.get_room_sources(doc)
        sources = core.filter_sources(all_sources, self.source_key)
        room_cache = {}
        loop_cache = {}

        band = self.band
        core.log_pick("selecting within " + core.describe_band(
            band if band is not None else (None, None)) +
            "  (" + str(self.band_label) + ")")

        added = 0
        already = 0
        misses = 0
        available = 0
        try:
            available = core.count_rooms_in_sources(sources, room_cache)
        except Exception as ex:
            available = 0
            core.log_pick("count_rooms_in_sources failed: " + str(ex))

        core.log_pick("session start: source_key=" + str(self.source_key) +
                      " sources=" + str(len(sources)) +
                      " rooms_available=" + str(available) +
                      " view=" + str(getattr(active_view, "Name", "?")))

        # Clicking a room needs no room list at all - Revit resolves the
        # pick - so pick mode runs whatever the collection reported. Only
        # box select, which works the rooms out itself, needs them.
        if self.mode == "pick":
            # One room per click. Revit highlights the room under the
            # cursor and Tab cycles through what is stacked there, which
            # is the behaviour asked for and the behaviour Revit gives
            # for free once the filter is right.
            host_only = (self.source_key == "host")
            if host_only:
                object_type = ObjectType.Element
                pick_filter = HostRoomFilter()
            else:
                object_type = ObjectType.LinkedElement
                pick_filter = LinkedRoomFilter()
            core.log_pick("pick mode: " +
                          ("host rooms" if host_only else "linked rooms"))

            # PickObjects, not PickObject: the multi-pick form is the one
            # that puts Revit's own **Finish** and **Cancel** buttons on
            # the options bar. Rooms still highlight and Tab still cycles
            # through stacked ones; clicking simply keeps adding to the
            # selection until Finish is pressed.
            references = []
            try:
                references = list(ui_document.Selection.PickObjects(
                    object_type, pick_filter,
                    "Click rooms - Tab cycles stacked rooms - "
                    "Finish when done"))
            except OperationCanceledException:
                core.log_pick("selection cancelled")
            except Exception as ex:
                core.log_pick("PickObjects raised: " + str(ex))
                self.status_text.Text = ("Selection failed: " + str(ex) +
                                         "  Press Diagnose for detail.")

            hits = []
            for reference in references:
                link_instance = None
                room = None
                try:
                    if host_only:
                        room = doc.GetElement(reference.ElementId)
                    else:
                        link_instance = doc.GetElement(reference.ElementId)
                        link_doc = link_instance.GetLinkDocument()
                        room = link_doc.GetElement(reference.LinkedElementId)
                except Exception as ex:
                    core.log_pick("could not resolve a picked room: " + str(ex))

                if room is None:
                    misses += 1
                    continue
                core.log_pick("picked: " +
                              (core.get_element_name(room) or "(unnamed)"))
                hits.append((link_instance, room))

            if hits:
                try:
                    new_entries = self.add_hits(hits)
                except Exception:
                    core.log_pick("add_hits raised:\n" + traceback.format_exc())
                    new_entries = (0, 0)
                added += new_entries[0]
                already += new_entries[1]

            msg = str(added) + " room(s) added. " + str(len(picked_rooms)) + " total."
            if already:
                msg += " " + str(already) + " already listed."
            if misses:
                msg += " " + str(misses) + " pick(s) did not resolve."
            if added == 0:
                msg += " Nothing was added - try Box Select or From List."
            if vis_error:
                msg += " (visibility: " + str(vis_error) + ")"
            self.status_text.Text = msg

        elif available == 0:
            self.status_text.Text = (
                "No placed rooms found in the selected source, so a box has "
                "nothing to work out. Try Select Rooms, or press Diagnose.")
            core.log_pick("aborted before PickBox: no rooms in source")

        else:
            while True:
                try:
                    box = ui_document.Selection.PickBox(
                        PickBoxStyle.Crossing,
                        "Drag a box around the rooms to add, or click one - "
                        "Escape when finished")
                except OperationCanceledException:
                    break
                except Exception as ex:
                    core.log_pick("PickBox raised: " + str(ex))
                    self.status_text.Text = ("Selection failed: " + str(ex) +
                                             "  Press Diagnose for detail.")
                    break

                try:
                    min_point = box.Min
                    max_point = box.Max
                    core.log_pick("box: min=({0:.2f},{1:.2f},{2:.2f}) "
                                  "max=({3:.2f},{4:.2f},{5:.2f})".format(
                                      min_point.X, min_point.Y, min_point.Z,
                                      max_point.X, max_point.Y, max_point.Z))
                except Exception as ex:
                    core.log_pick("could not read box: " + str(ex))
                    continue

                hits = []
                if core.is_click_not_box(min_point, max_point):
                    link, room = core.find_room_in_sources(
                        sources, min_point, room_cache, loop_cache, band)
                    if room is not None:
                        hits = [(link, room)]
                else:
                    hits = core.rooms_in_box(sources, min_point, max_point,
                                             room_cache, loop_cache, band)

                core.log_pick("hits: " + str(len(hits)))

                if not hits:
                    misses += 1
                    self.status_text.Text = (
                        "Nothing in that selection. " + str(available) +
                        " room(s) available in the chosen source. " +
                        str(len(picked_rooms)) + " listed so far.")
                    continue

                try:
                    new_entries = self.add_hits(hits)
                except Exception:
                    # An exception escaping here used to kill Execute
                    # outright, which skipped the window.Show() at the end
                    # and left the tool looking like it had vanished.
                    core.log_pick("add_hits raised:\n" + traceback.format_exc())
                    new_entries = (0, 0)
                added += new_entries[0]
                already += new_entries[1]

                self.status_text.Text = (str(added) + " added this session, " +
                                         str(len(picked_rooms)) +
                                         " listed. Escape when finished.")

            msg = str(added) + " room(s) added. " + str(len(picked_rooms)) + " total."
            if already:
                msg += " " + str(already) + " already listed."
            if misses:
                msg += " " + str(misses) + " empty selection(s)."
            if added == 0:
                msg += " Nothing was added - From List always works."
            if vis_error:
                msg += " (visibility: " + vis_error + ")"
            self.status_text.Text = msg

        if restore_cats or restore_links:
            trest = Transaction(doc, "RevoBIM - restore view visibility")
            try:
                trest.Start()
                core.restore_category_visibility(active_view, restore_cats)
                core.restore_link_overrides(active_view, restore_links)
                trest.Commit()
            except Exception as ex:
                try:
                    if trest.HasStarted() and not trest.HasEnded():
                        trest.RollBack()
                except Exception:
                    pass
                core.log_pick("restore visibility failed: " + str(ex))

        try:
            core.log_pick("session end: picked_rooms=" + str(len(picked_rooms)) +
                          " list_items=" + str(self.list_box.Items.Count))
        except Exception:
            pass

        try:
            self.window.Show()
            self.window.Activate()
        except Exception:
            pass

    def add_hits(self, hits):
        """Adds (link, room) pairs to the list. Returns (added, already).

        **Nothing is written to the model here.** Selecting rooms is a
        read-only act: no separation lines, no spaces, no transaction at
        all. Everything is created when Create Spaces is pressed, so the
        list can be built up, corrected and cleared with no trace left
        behind."""
        added = 0
        already = 0
        # The membership test was rebuilding a list of every listed key for
        # every hit - quadratic, and a box over a floor is hundreds of
        # hits. Built once, added to as we go.
        existing_keys = set(p.key() for p in picked_rooms)

        for link_instance, room in hits:
            room_label = core.get_element_name(room) or "(unnamed)"

            try:
                if link_instance is None:
                    source_title = "This model"
                    link_id = None
                else:
                    source_title = link_instance.GetLinkDocument().Title
                    link_id = link_instance.Id

                level_name = ""
                try:
                    level_name = core.get_element_name(room.Level)
                except Exception:
                    level_name = ""

                entry = PickedRoom(
                    link_id,
                    source_title,
                    room.Id,
                    core.get_element_name(room),
                    core.get_room_number(room),
                    level_name,
                )
            except Exception as ex:
                core.log_pick("  SKIP " + room_label +
                              " - could not build entry: " + str(ex))
                continue

            if entry.key() in existing_keys:
                already += 1
                core.log_pick("  already listed: " + room_label)
                continue
            existing_keys.add(entry.key())

            picked_rooms.append(entry)

            try:
                text = entry.display()
            except Exception as ex:
                text = room_label
                core.log_pick("  display() failed for " + room_label +
                              ": " + str(ex))
            try:
                self.list_box.Items.Add(text)
                core.log_pick("  ADDED " + text + "  (list now holds " +
                              str(self.list_box.Items.Count) + ")")
            except Exception as ex:
                core.log_pick("  LIST ADD FAILED for " + room_label +
                              ": " + str(ex))
            added += 1

        return added, already

    def GetName(self):
        return "RevoBIM Space Creator - select rooms"


def run_automatic(options, active_view, status_text, progress=None):
    """Places spaces into every room that does not already have one.

    Rooms are taken from this model, from the loaded links, or both. In an
    MEP model the rooms usually live in the architectural link rather than
    in the model itself, which is why 'links' is part of the default.

    Work is committed in chunks rather than one transaction for the whole
    batch: it keeps the progress bar honest, and one room Revit refuses
    cannot roll back every room before it."""
    host_rooms = []
    link_records = []

    if options.room_source in ("host", "both"):
        host_rooms = core.get_rooms(doc, options.scope, active_view)
    if options.room_source in ("links", "both"):
        link_records = core.get_linked_room_records(doc, options.scope, active_view)

    if not host_rooms and not link_records:
        where = {"host": "this model",
                 "links": "the loaded links",
                 "both": "this model or the loaded links"}[options.room_source]
        scope_word = ("the current view" if options.scope == "current_view"
                      else "the whole project")
        message = "No placed rooms found in " + where + " for " + scope_word + "."
        if options.room_source == "host":
            message += " If the rooms are in an architectural link, " \
                       "set Rooms From to include links."
        status_text.Text = message
        return

    spaces = core.get_all_spaces(doc)

    if options.clear_existing:
        # Everything in scope is about to be deleted, so nothing counts as
        # already placed.
        unplaced_rooms, placed_rooms = host_rooms, []
        unplaced_records, placed_records = link_records, []
    else:
        unplaced_rooms, placed_rooms = core.rooms_without_spaces(
            doc, host_rooms, spaces)
        unplaced_records, placed_records = core.linked_records_without_spaces(
            doc, link_records, spaces)

    total = len(unplaced_rooms) + len(unplaced_records)
    already = len(placed_rooms) + len(placed_records)

    if total == 0:
        status_text.Text = ("Every room found already has a space (" +
                            str(already) + " checked). Nothing to do.")
        return

    host_levels = list(FilteredElementCollector(doc).OfClass(Level))

    if progress:
        progress.start(total, "Placing spaces")

    tg = TransactionGroup(doc, "RevoBIM Space Creator - automatic")
    tg.Start()

    created_rows = []
    lines_drawn = 0
    push_ok = 0
    push_failed = 0
    failed = 0
    unenclosed = 0
    made_spaces = []
    plane_cache = {}
    first_error = None

    try:
        if options.clear_existing:
            t0 = Transaction(doc, "RevoBIM - clear existing spaces and lines")
            t0.Start()
            core.apply_warning_suppression(t0)
            existing_spaces, existing_lines = core.get_existing_spaces_and_lines(
                doc, options.scope, active_view)
            for el in existing_lines:
                try:
                    doc.Delete(el.Id)
                except Exception:
                    pass
            for el in existing_spaces:
                try:
                    doc.Delete(el.Id)
                except Exception:
                    pass
            t0.Commit()

        # --- rooms in this model -------------------------------------
        for start in range(0, len(unplaced_rooms), CHUNK_SIZE):
            chunk = unplaced_rooms[start:start + CHUNK_SIZE]
            t = Transaction(doc, "RevoBIM - place spaces")
            t.Start()
            core.apply_warning_suppression(t)

            # Boundaries for the whole chunk first, then one regenerate,
            # then the spaces. Revit does not treat a separation line as
            # bounding until it regenerates, so placing a space straight
            # after drawing its perimeter reports "not in a properly
            # enclosed region" even though the perimeter is there.
            if options.make_lines:
                for room in chunk:
                    try:
                        drawn, line_error = core.create_separation_lines_for_room(
                            doc, room, active_view, plane_cache)
                        lines_drawn += drawn
                        if line_error and first_error is None:
                            first_error = line_error
                    except Exception:
                        pass
                doc.Regenerate()

            for room in chunk:
                space, err = core.create_space_for_room(doc, room)
                if space is None:
                    failed += 1
                    if first_error is None:
                        first_error = err
                    continue

                if options.inherit_name:
                    core.inherit_name_from_room(space, room)
                if options.workset_id is not None:
                    core.set_element_workset(doc, space, options.workset_id)
                if options.push_ceiling:
                    ok, _msg = core.push_space_to_ceiling_underside(doc, space, room)
                    if ok:
                        push_ok += 1
                    else:
                        push_failed += 1

                created_rows.append(core.describe_space(space, room))
                made_spaces.append(space)
            doc.Regenerate()
            for space in made_spaces:
                if not core.space_is_enclosed(space):
                    unenclosed += 1
            del made_spaces[:]
            t.Commit()
            # Between transactions, never inside one.
            if progress:
                progress.advance(len(chunk))

        # --- rooms in the links --------------------------------------
        for start in range(0, len(unplaced_records), CHUNK_SIZE):
            chunk = unplaced_records[start:start + CHUNK_SIZE]
            t = Transaction(doc, "RevoBIM - place spaces from links")
            t.Start()
            core.apply_warning_suppression(t)

            if options.make_lines:
                for record in chunk:
                    try:
                        curve_loops = core.linked_room_curve_loops(
                            record["room"], record["transform"])
                        if curve_loops:
                            record_level = _host_level_for_z(
                                host_levels, record["host_point"].Z)
                            drawn, line_error = \
                                core.create_separation_lines_for_curve_loops(
                                    doc, curve_loops, record["host_point"].Z,
                                    active_view, record_level, plane_cache)
                            lines_drawn += drawn
                            if line_error and first_error is None:
                                first_error = line_error
                    except Exception:
                        pass
                doc.Regenerate()

            for record in chunk:
                room = record["room"]
                host_point = record["host_point"]
                host_level = _host_level_for_z(host_levels, host_point.Z)
                if host_level is None:
                    failed += 1
                    if first_error is None:
                        first_error = "no host level for a linked room"
                    continue

                space, err = core.create_space_at_point(doc, host_level, host_point)
                if space is None:
                    failed += 1
                    if first_error is None:
                        first_error = err
                    continue

                if options.inherit_name:
                    core.inherit_name_from_room(space, room)
                if options.workset_id is not None:
                    core.set_element_workset(doc, space, options.workset_id)
                if options.push_ceiling:
                    ok, _msg = core.push_space_to_ceiling_underside_at(
                        doc, space, host_level, host_point)
                    if ok:
                        push_ok += 1
                    else:
                        push_failed += 1

                created_rows.append(core.describe_space(space, room))
                made_spaces.append(space)
            doc.Regenerate()
            for space in made_spaces:
                if not core.space_is_enclosed(space):
                    unenclosed += 1
            del made_spaces[:]
            t.Commit()
            if progress:
                progress.advance(len(chunk))

        tg.Assimilate()
    except Exception as ex:
        tg.RollBack()
        if progress:
            progress.finish()
        status_text.Text = "Failed: " + str(ex)
        return

    if progress:
        progress.finish()

    created = len(created_rows)
    try:
        warning = core.space_visibility_warning(doc, active_view)
        if warning:
            core.log_pick("  WARNING: " + warning)
    except Exception:
        warning = ""
    summary = str(created) + " space(s) placed"
    if link_records:
        summary += " (" + str(len(unplaced_records)) + " from links)"
    if already:
        summary += ", " + str(already) + " room(s) already had one"
    if options.make_lines:
        summary += ", " + str(lines_drawn) + " perimeter(s) drawn"
    if options.push_ceiling:
        summary += ", " + str(push_ok) + " pushed to ceiling underside"
        if push_failed:
            summary += " (" + str(push_failed) + " could not be)"
    if unenclosed:
        summary += ". " + str(unenclosed) + " not enclosed"
    if failed:
        summary += ". " + str(failed) + " room(s) failed"
        if first_error:
            summary += " - first error: " + first_error
    if warning:
        summary += "  NOTE: " + warning
    core.log_pick("CREATE (automatic) done: created=" + str(created) +
                  " failed=" + str(failed))
    status_text.Text = summary

    try:
        show_results_window(created_rows, already)
    except Exception:
        logger.error(traceback.format_exc())



def _host_level_for_z(host_levels, z_value):
    best = None
    best_diff = None
    for lvl in host_levels:
        elevation = core.level_elevation(lvl)
        if elevation is None:
            continue
        diff = abs(elevation - z_value)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = lvl
    return best


def _resolve_entry(entry, host_levels):
    """Turns a listed room back into everything needed to place a space.
    Returns (record_or_None, error)."""
    if entry.link_instance_id is None:
        room = doc.GetElement(entry.room_id)
        if room is None:
            return None, "room no longer found in this model"
        try:
            point = room.Location.Point
        except Exception:
            return None, "room has no location point"
        try:
            level = room.Level
        except Exception:
            level = _host_level_for_z(host_levels, point.Z)
        return {"entry": entry, "room": room, "link": None,
                "transform": None, "point": point, "level": level}, None

    link_instance = doc.GetElement(entry.link_instance_id)
    if link_instance is None:
        return None, "linked model instance no longer found"
    link_doc = link_instance.GetLinkDocument()
    if link_doc is None:
        return None, "linked document not loaded"
    room = link_doc.GetElement(entry.room_id)
    if room is None:
        return None, "room no longer found in link"

    try:
        transform = link_instance.GetTotalTransform()
        point = transform.OfPoint(room.Location.Point)
    except Exception as ex:
        return None, "could not place the room in host coordinates: " + str(ex)

    level = _host_level_for_z(host_levels, point.Z)
    if level is None:
        return None, "no host level found"
    return {"entry": entry, "room": room, "link": link_instance,
            "transform": transform, "point": point, "level": level}, None


def run_manual(options, active_view, status_text, list_box, progress=None):
    if not picked_rooms:
        status_text.Text = "Pick at least one room first."
        return

    host_levels = list(FilteredElementCollector(doc).OfClass(Level))

    warning = ""
    try:
        warning = core.space_visibility_warning(doc, active_view)
        if warning:
            core.log_pick("  WARNING: " + warning)
    except Exception:
        pass

    core.log_pick("CREATE (manual): " + str(len(picked_rooms)) +
                  " room(s), boundary=" + str(options.boundary_mode) +
                  ", inherit_name=" + str(options.inherit_name) +
                  ", push_ceiling=" + str(options.push_ceiling) +
                  ", workset=" + str(options.workset_name or "(none)") +
                  ", host levels=" + str(len(host_levels)) +
                  ", view=" + str(getattr(active_view, "Name", "?")))

    records = []
    failed = 0
    first_error = None
    for entry in picked_rooms:
        record, error = _resolve_entry(entry, host_levels)
        if record is None:
            failed += 1
            if first_error is None:
                first_error = error
            core.log_pick("  " + str(entry.room_name) + ": FAILED - " + str(error))
        else:
            records.append(record)

    if not records:
        status_text.Text = "Nothing could be resolved. " + (first_error or "")
        return

    if progress:
        progress.start(len(records), "Creating spaces")

    tg = TransactionGroup(doc, "RevoBIM Space Creator - manual")
    tg.Start()
    created = 0
    unenclosed = 0
    lines_total = 0

    t = Transaction(doc, "RevoBIM - space from room manual")
    t.Start()
    core.apply_warning_suppression(t)
    try:
        # --- pass 1: every boundary first ----------------------------
        #
        # All the separation lines are drawn before any space is placed,
        # and the document is regenerated in between. Revit does not see
        # a line drawn moments earlier as bounding until it regenerates,
        # so placing a space straight after drawing its perimeter gives
        # "Space is not in a properly enclosed region" every time - the
        # boundary was there, Revit just had not looked yet.
        if options.boundary_mode != "native":
            plane_cache = {}
            for record in records:
                name = str(record["entry"].room_name)
                level = record["level"]
                try:
                    if record["link"] is None:
                        drawn, err = core.create_separation_lines_for_room(
                            doc, record["room"], active_view, plane_cache)
                    else:
                        loops = core.linked_room_curve_loops(
                            record["room"], record["transform"])
                        # The level is passed so the lines land on the very
                        # level the space will be created on. Drawing them
                        # at the room's own point Z instead leaves them a
                        # little off it, and a line that does not share a
                        # space's level does not bound it.
                        drawn, err = core.create_separation_lines_for_curve_loops(
                            doc, loops, record["point"].Z, active_view, level,
                            plane_cache)
                    lines_total += drawn
                    try:
                        core.log_pick("  lines for " + name + ": " + str(drawn) +
                                      "  room Z " +
                                      str(int(record["point"].Z * 304.8)) +
                                      "mm, level " +
                                      str(core.get_element_name(level)) + " at " +
                                      str(int((core.level_elevation(level) or 0.0) * 304.8)) + "mm" +
                                      (" err=" + str(err) if err else ""))
                    except Exception:
                        core.log_pick("  lines for " + name + ": " + str(drawn))
                except Exception as ex:
                    core.log_pick("  lines FAILED for " + name + ": " + str(ex))

            doc.Regenerate()
            core.log_pick("  regenerated after drawing " + str(lines_total) +
                          " perimeter(s)")

        # --- pass 2: the spaces --------------------------------------
        made = []
        for record in records:
            entry = record["entry"]
            name = str(entry.room_name)
            space, err = core.create_space_at_point(doc, record["level"],
                                                    record["point"])
            if space is None:
                failed += 1
                if first_error is None:
                    first_error = err
                core.log_pick("  " + name + ": FAILED - NewSpace refused: " +
                              str(err))
                if progress:
                    progress.done += 1
                continue

            if options.inherit_name:
                core.inherit_name_from_room(space, record["room"])
            if options.workset_id is not None:
                core.set_element_workset(doc, space, options.workset_id)
            if options.push_ceiling:
                core.push_space_to_ceiling_underside_at(
                    doc, space, record["level"], record["point"])

            created += 1
            made.append((name, space))
            core.log_pick("  " + name + ": OK - space id " +
                          str(core.eid_value(space.Id)))
            if progress:
                progress.done += 1

        # --- pass 3: did they actually bound? ------------------------
        doc.Regenerate()
        for name, space in made:
            if not core.space_is_enclosed(space):
                unenclosed += 1
                detail = ""
                try:
                    space_level = space.Level
                    detail = ("  space level " +
                              str(core.get_element_name(space_level)) +
                              " at " +
                              str(int((core.level_elevation(space_level) or 0.0) * 304.8)) + "mm")
                except Exception:
                    pass
                core.log_pick("  " + name + ": created but NOT enclosed." +
                              detail)

        t.Commit()
        tg.Assimilate()
    except Exception as ex:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        tg.RollBack()
        if progress:
            progress.finish()
        core.log_pick("CREATE (manual) THREW, everything rolled back:\n" +
                      traceback.format_exc())
        status_text.Text = "Failed: " + str(ex)
        return

    if progress:
        progress.finish()

    list_box.Items.Clear()
    del picked_rooms[:]

    summary = str(created) + " space(s) created"
    if lines_total:
        summary += ", " + str(lines_total) + " perimeter(s) drawn"
    if unenclosed:
        summary += ". " + str(unenclosed) + " reported not enclosed - the " \
                   "space exists and is placed, but Revit is not treating " \
                   "the perimeter as bounding it; see the debug log for the " \
                   "line and space levels"
    if failed:
        summary += ". " + str(failed) + " failed"
        if first_error:
            summary += " - first error: " + str(first_error)
    if warning:
        summary += "  NOTE: " + warning
    core.log_pick("CREATE (manual) done: created=" + str(created) +
                  " unenclosed=" + str(unenclosed) + " failed=" + str(failed))
    status_text.Text = summary


def run_delete_lines(status_text, progress=None):
    """Deletes the space separation lines inside every listed room."""
    if not picked_rooms:
        status_text.Text = "The list is empty - nothing to clear."
        return

    host_levels = list(FilteredElementCollector(doc).OfClass(Level))
    records = []
    for entry in picked_rooms:
        record, error = _resolve_entry(entry, host_levels)
        if record is not None:
            records.append(record)
        else:
            core.log_pick("  delete lines: " + str(entry.room_name) +
                          " unresolved - " + str(error))

    if not records:
        status_text.Text = "None of the listed rooms could be resolved."
        return

    core.log_pick("DELETE LINES: " + str(len(records)) + " room(s)")

    if progress:
        progress.start(len(records), "Deleting separation lines")

    deleted = 0
    tg = TransactionGroup(doc, "RevoBIM Space Creator - delete separation lines")
    tg.Start()
    t = Transaction(doc, "RevoBIM - delete space separation lines")
    t.Start()
    core.apply_warning_suppression(t)
    try:
        deleted, error = core.delete_separation_lines_for_records(doc, records)
        if error:
            core.log_pick("  some lines refused deletion: " + str(error))
        t.Commit()
        tg.Assimilate()
    except Exception as ex:
        try:
            if t.HasStarted() and not t.HasEnded():
                t.RollBack()
        except Exception:
            pass
        tg.RollBack()
        if progress:
            progress.finish()
        core.log_pick("DELETE LINES threw:\n" + traceback.format_exc())
        status_text.Text = "Failed: " + str(ex)
        return

    if progress:
        progress.finish()

    core.log_pick("DELETE LINES done: " + str(deleted) + " line(s)")
    status_text.Text = (str(deleted) + " separation line(s) deleted from " +
                        str(len(records)) + " room(s).")


class AddFromListHandler(IExternalEventHandler):
    """Adds rooms chosen in the From List window.

    Read-only, like selecting in the view: nothing is drawn or created
    until Create Spaces. Set `entries` on the UI thread before raising."""

    def __init__(self, list_box, status_text):
        self.list_box = list_box
        self.status_text = status_text
        self.entries = []

    def Execute(self, uiapp):
        chosen = self.entries
        self.entries = []
        if not chosen:
            return

        added = 0
        already = 0
        existing_keys = set(p.key() for p in picked_rooms)

        for record in chosen:
            link_instance = record["link"]
            try:
                entry = PickedRoom(
                    link_instance.Id if link_instance is not None else None,
                    record["link_title"],
                    record["room_id"],
                    record["name"],
                    record["number"],
                    record.get("level", ""),
                )
            except Exception as ex:
                core.log_pick("  from list: could not build entry: " + str(ex))
                continue

            if entry.key() in existing_keys:
                already += 1
                continue
            existing_keys.add(entry.key())

            picked_rooms.append(entry)
            try:
                self.list_box.Items.Add(entry.display())
            except Exception as ex:
                core.log_pick("  from list: list add failed: " + str(ex))
            added += 1

        msg = str(added) + " room(s) added. " + str(len(picked_rooms)) + " total."
        if already:
            msg += " " + str(already) + " already listed."
        self.status_text.Text = msg
        core.log_pick("from list: added=" + str(added) +
                      " already=" + str(already) +
                      " total=" + str(len(picked_rooms)))

    def GetName(self):
        return "RevoBIM Space Creator - add rooms from list"


class SpaceFilter(ISelectionFilter):
    """Allows only MEP spaces in this document. Looked up by category id
    rather than by class so it does not depend on which namespace Space
    lives in on a given release."""

    def AllowElement(self, element):
        try:
            category = element.Category
            if category is None:
                return False
            spaces = Category.GetCategory(doc, BuiltInCategory.OST_MEPSpaces)
            return core.eid_value(category.Id) == core.eid_value(spaces.Id)
        except Exception:
            return False

    def AllowReference(self, reference, position):
        return True


class PushUpHandler(IExternalEventHandler):
    """Lets the user select spaces in the model and works out how far up
    each can go. It writes nothing: every result becomes a pending value
    on the grid row, or a flag with the reason, for Apply to act on."""

    def __init__(self, grid, status_text):
        self.grid = grid
        self.status_text = status_text

    def Execute(self, uiapp):
        ui_document = uiapp.ActiveUIDocument
        references = []
        try:
            references = list(ui_document.Selection.PickObjects(
                ObjectType.Element, SpaceFilter(),
                "Select the spaces to push up - Finish when done"))
        except OperationCanceledException:
            self.status_text.Text = "Selection cancelled."
            return
        except Exception as ex:
            self.status_text.Text = "Selection failed: " + str(ex)
            core.log_pick("push up: PickObjects raised: " + str(ex))
            return

        if not references:
            self.status_text.Text = "No spaces selected."
            return

        if not self.grid.rows:
            self.grid.load()

        floors = core.collect_floor_boxes(doc)
        core.log_pick("PUSH UP: " + str(len(references)) + " selected, " +
                      str(len(floors)) + " floor(s) in the model")

        pushed = 0
        flagged = 0
        missing = 0
        for reference in references:
            row = self.grid.row_by_id(core.eid_value(reference.ElementId))
            if row is None:
                missing += 1
                continue
            new_limit, target, reason = core.compute_push_target(
                row, floors, self.grid.rows)
            label = (row["number"] + " " + row["name"]).strip()
            if reason:
                row["flag"] = reason
                row["status"] = ""
                flagged += 1
                core.log_pick("  " + label + ": FLAGGED - " + reason)
                continue
            row["flag"] = ""
            row["pending_limit"] = new_limit
            # Anchor the top to the space's own level so the offset alone
            # carries the height.
            try:
                own_level = doc.GetElement(row["id"]).Level
                row["pending_upper_id"] = own_level.Id
                row["pending_upper"] = core.get_element_name(own_level)
            except Exception:
                pass
            row["status"] = ("push to " + str(core.mm(target)) + "mm (" +
                             str(row["limit_offset"]) + " -> " +
                             str(new_limit) + ")")
            pushed += 1
            core.log_pick("  " + label + ": limit " + str(row["limit_offset"]) +
                          " -> " + str(new_limit) + "mm")

        self.grid.refresh()
        msg = (str(pushed) + " space(s) set to push, " + str(flagged) +
               " flagged. Review the list, then Apply.")
        if missing:
            msg += " " + str(missing) + " not in the list - press Refresh."
        self.status_text.Text = msg

    def GetName(self):
        return "RevoBIM Space Creator - push spaces up"


def run_manage_apply(grid, status_text, progress=None):
    """Writes every pending row to the model in chunks, verifies each by
    reading it back, and reports every change made."""
    pending = grid.pending_rows()
    if not pending:
        status_text.Text = "Nothing pending to apply."
        return

    core.log_pick("APPLY (manage): " + str(len(pending)) + " space(s)")

    if progress:
        progress.start(len(pending), "Applying space changes")

    report = []
    applied = 0
    failed = 0

    tg = TransactionGroup(doc, "RevoBIM Space Creator - apply space changes")
    tg.Start()
    try:
        for start in range(0, len(pending), CHUNK_SIZE):
            chunk = pending[start:start + CHUNK_SIZE]
            t = Transaction(doc, "RevoBIM - space offsets")
            t.Start()
            core.apply_warning_suppression(t)
            outcomes = []
            for row in chunk:
                ok, msg = core.apply_space_edit(doc, row, None)
                outcomes.append((row, ok, msg))
            t.Commit()

            # A commit regenerates; only now is a read-back meaningful.
            for row, ok, msg in outcomes:
                label_num = row["number"]
                label_name = row["name"]
                if not ok:
                    failed += 1
                    row["flag"] = msg
                    row["status"] = ""
                    report.append((row["level"], label_num, label_name,
                                   "FAILED", msg))
                    core.log_pick("  " + label_num + ": FAILED - " + msg)
                    continue
                verified, why = core.verify_space_edit(doc, row)
                if not verified:
                    failed += 1
                    row["flag"] = "did not stick: " + why
                    row["status"] = ""
                    report.append((row["level"], label_num, label_name,
                                   "NOT VERIFIED", why))
                    core.log_pick("  " + label_num + ": NOT VERIFIED - " + why)
                    continue
                applied += 1
                report.append((row["level"], label_num, label_name,
                               "changed", msg))
                core.log_pick("  " + label_num + ": " + msg)
                # Fold the change into the row so the grid shows reality.
                if row["pending_base"] is not None:
                    row["base_offset"] = row["pending_base"]
                if row["pending_limit"] is not None:
                    row["limit_offset"] = row["pending_limit"]
                if row["pending_upper_id"] is not None:
                    row["upper_level_id"] = row["pending_upper_id"]
                    row["upper_level"] = row["pending_upper"]
                row["pending_base"] = None
                row["pending_limit"] = None
                row["pending_upper_id"] = None
                row["pending_upper"] = ""
                row["status"] = "applied"
                row["flag"] = ""

            if progress:
                progress.advance(len(chunk))

        tg.Assimilate()
    except Exception as ex:
        tg.RollBack()
        if progress:
            progress.finish()
        core.log_pick("APPLY (manage) THREW, rolled back:\n" +
                      traceback.format_exc())
        status_text.Text = "Failed: " + str(ex)
        return

    if progress:
        progress.finish()

    # Heights are computed by Revit; re-read so the grid shows them.
    grid.load()

    summary = str(applied) + " space(s) changed"
    if failed:
        summary += ", " + str(failed) + " failed or did not verify (flagged)"
    core.log_pick("APPLY (manage) done: applied=" + str(applied) +
                  " failed=" + str(failed))
    status_text.Text = summary

    try:
        show_change_report(report)
    except Exception:
        logger.error(traceback.format_exc())


CHANGE_REPORT_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="RevoBIM Space Creator - changes made"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent"
        WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
        SizeToContent="Height" Width="720" ShowInTaskbar="True">

  <Window.Resources>
    <!--SCROLLBARS-->
  </Window.Resources>

  <Border CornerRadius="6" Background="{WINDOW_BG}" BorderBrush="#4A4A50" BorderThickness="1">
    <DockPanel LastChildFill="True">
      <Border DockPanel.Dock="Top" Background="{BAR_BG}" CornerRadius="6,6,0,0" Height="52"
              Name="ChangeHeaderBar">
        <Grid Margin="14,0,10,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <StackPanel Orientation="Vertical" VerticalAlignment="Center">
            <TextBlock Text="RevoBIM" FontSize="20" FontWeight="Bold" Foreground="{BLUE}"/>
            <TextBlock Text="Changes made" FontSize="13" Foreground="{ORANGE}" Margin="0,-2,0,0"/>
          </StackPanel>
          <Button Grid.Column="1" Name="ChangeCloseButton" Content="&#x2715;" Width="26" Height="26"
                  Background="Transparent" BorderThickness="0" Foreground="{TEXT_MUTED}" FontSize="13"
                  Cursor="Hand"/>
        </Grid>
      </Border>
      <Border DockPanel.Dock="Bottom" Background="{BAR_BG}" CornerRadius="0,0,6,6" Height="48">
        <Grid Margin="14,0,14,0">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*" />
            <ColumnDefinition Width="Auto" />
          </Grid.ColumnDefinitions>
          <TextBlock Name="ChangeCount" Foreground="{TEXT_MUTED}" FontSize="11" VerticalAlignment="Center"/>
          <Button Grid.Column="1" Name="ChangeOkButton" Content="Close" Width="90" Height="30"
                  Background="{CARD_BG}" Foreground="{TEXT}" BorderThickness="1"
                  BorderBrush="{BORDER}" Cursor="Hand"/>
        </Grid>
      </Border>
      <StackPanel Margin="16,14,16,10">
        <Grid Margin="0,0,0,2">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="130"/><ColumnDefinition Width="80"/>
            <ColumnDefinition Width="170"/><ColumnDefinition Width="100"/>
            <ColumnDefinition Width="*"/>
          </Grid.ColumnDefinitions>
          <TextBlock Text="Level" Foreground="{TEXT_MUTED}" FontSize="11" Margin="6,0,0,0"/>
          <TextBlock Grid.Column="1" Text="Number" Foreground="{TEXT_MUTED}" FontSize="11" Margin="6,0,0,0"/>
          <TextBlock Grid.Column="2" Text="Name" Foreground="{TEXT_MUTED}" FontSize="11" Margin="6,0,0,0"/>
          <TextBlock Grid.Column="3" Text="Result" Foreground="{TEXT_MUTED}" FontSize="11" Margin="6,0,0,0"/>
          <TextBlock Grid.Column="4" Text="Change" Foreground="{TEXT_MUTED}" FontSize="11" Margin="6,0,0,0"/>
        </Grid>
        <ListBox Name="ChangeList" Height="320" Background="{FIELD_BG}" Foreground="{TEXT}"
                 BorderBrush="{BORDER}" BorderThickness="1" HorizontalContentAlignment="Stretch"/>
      </StackPanel>
    </DockPanel>
  </Border>
</Window>
"""


def show_change_report(report):
    """Lists every change Apply made, and every one it could not."""
    if not report:
        return
    window = XamlReader.Parse(_themed(CHANGE_REPORT_XAML))
    find = window.FindName
    list_box = find("ChangeList")

    widths = (130, 80, 170, 100, 0)
    for level, number, name, result, change in report:
        grid = Grid()
        for width in widths:
            column = ColumnDefinition()
            column.Width = GridLength(width) if width else \
                GridLength(1, GridUnitType.Star)
            grid.ColumnDefinitions.Add(column)
        colour = theme.GREEN if result == "changed" else theme.RED
        for index, text in enumerate((level, number, name, result, change)):
            block = TextBlock()
            block.Text = str(text or "")
            block.Foreground = _brush(colour if index == 3 else theme.TEXT)
            block.Margin = Thickness(6, 2, 4, 2)
            block.TextTrimming = TextTrimming.CharacterEllipsis
            Grid.SetColumn(block, index)
            grid.Children.Add(block)
        list_box.Items.Add(grid)

    good = len([r for r in report if r[3] == "changed"])
    find("ChangeCount").Text = (str(good) + " changed, " +
                                str(len(report) - good) + " not")

    def on_close(sender, args):
        window.Close()
    find("ChangeCloseButton").Click += on_close
    find("ChangeOkButton").Click += on_close

    def on_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    find("ChangeHeaderBar").MouseLeftButtonDown += on_drag

    try:
        helper = WindowInteropHelper(window)
        helper.Owner = revit.uiapp.MainWindowHandle
    except Exception:
        pass
    window.Show()


class RunHandler(IExternalEventHandler):
    """One handler for both tabs and for line cleanup. `mode` is set on the
    UI thread before the event is raised, along with an Options snapshot -
    the handler never reads the window itself."""

    def __init__(self, status_text, list_box, progress=None, grid=None):
        self.status_text = status_text
        self.list_box = list_box
        self.progress = progress
        self.grid = grid
        self.mode = "auto"
        self.options = None

    def Execute(self, uiapp):
        active_view = doc.ActiveView
        try:
            if self.mode == "delete_lines":
                run_delete_lines(self.status_text, self.progress)
                return
            if self.mode == "manage_apply":
                run_manage_apply(self.grid, self.status_text, self.progress)
                return
            if self.options is None:
                return
            if self.mode == "auto":
                run_automatic(self.options, active_view, self.status_text,
                              self.progress)
            else:
                run_manual(self.options, active_view, self.status_text,
                           self.list_box, self.progress)
        except Exception as ex:
            if self.progress:
                try:
                    self.progress.finish()
                except Exception:
                    pass
            try:
                self.status_text.Text = "Failed: " + str(ex)
            except Exception:
                pass
            logger.error(traceback.format_exc())

    def GetName(self):
        return "RevoBIM Space Creator - run"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _window

    window = build_window()
    _window = window

    # Owned by Revit's main window, or a modeless window slips behind Revit
    # and reads as a crash.
    try:
        helper = WindowInteropHelper(window)
        helper.Owner = revit.uiapp.MainWindowHandle
    except Exception:
        pass

    find = window.FindName
    header = find("HeaderBar")
    status_text = find("StatusText")
    list_box = find("RoomList")
    tabs = find("MainTabs")
    action_button = find("ActionButton")

    def on_header_drag(sender, args):
        try:
            window.DragMove()
        except Exception:
            pass
    header.MouseLeftButtonDown += on_header_drag

    wire_resize_grips(window)

    def on_close(sender, args):
        window.Close()
    find("CloseButton").Click += on_close

    worksets = core.get_user_worksets(doc)
    combo = find("WorksetCombo")
    resolve_selected_workset = wire_workset_combo(combo, worksets)

    # Restore the workset chosen last time, if it still exists.
    remembered = core.load_settings().get("workset_name", "")
    if remembered:
        for index in range(combo.Items.Count):
            if combo.Items[index] == remembered:
                combo.SelectedIndex = index
                combo.Text = remembered
                break

    pick_handler = PickRoomHandler(window, list_box, status_text)
    pick_event = ExternalEvent.Create(pick_handler)
    progress = Progress(window)
    manage_grid = ManageGrid(window, status_text)
    run_handler = RunHandler(status_text, list_box, progress, manage_grid)
    run_event = ExternalEvent.Create(run_handler)

    # Read Rooms From - this model, or a specific link, or all of them.
    source_combo = find("RoomSourceCombo")
    room_sources = core.get_room_sources(doc)
    source_keys = ["all"]
    source_combo.Items.Add("All sources")
    for source in room_sources:
        source_combo.Items.Add(source["label"])
        source_keys.append(source["key"])
    source_combo.SelectedIndex = 0

    def selected_source_key():
        index = source_combo.SelectedIndex
        if index < 0 or index >= len(source_keys):
            return "all"
        return source_keys[index]

    # Rooms on: the view's own range by default, or a level by hand.
    level_combo = find("LevelCombo")
    level_entries = []          # (label, band_or_None)

    def rebuild_levels():
        level_combo.Items.Clear()
        del level_entries[:]

        level_entries.append(("This view (what it shows)", "view"))
        level_combo.Items.Add("This view (what it shows)")
        level_entries.append(("All levels", None))
        level_combo.Items.Add("All levels")

        try:
            sources = core.filter_sources(core.get_room_sources(doc),
                                          selected_source_key())
            for name, elevation in core.get_source_levels(sources):
                label = name + "  (" + str(int(elevation * 304.8)) + "mm)"
                level_entries.append((label, core.band_for_elevation(elevation)))
                level_combo.Items.Add(label)
        except Exception:
            logger.error(traceback.format_exc())
        level_combo.SelectedIndex = 0

    rebuild_levels()

    def on_source_changed(sender, args):
        rebuild_levels()
    source_combo.SelectionChanged += on_source_changed

    def selected_band():
        """Returns (band, label). 'view' is resolved against the active
        view at the moment of picking, not when the window opened."""
        index = level_combo.SelectedIndex
        if index < 0 or index >= len(level_entries):
            return None, "every level"
        label, value = level_entries[index]
        if value == "view":
            return core.band_for_view(doc.ActiveView), label
        return value, label

    def start_pick(mode):
        # Snapshot on the UI thread - the handler must not reach back
        # into WPF.
        pick_handler.mode = mode
        pick_handler.source_key = selected_source_key()
        band, label = selected_band()
        pick_handler.band = band
        pick_handler.band_label = label
        pick_event.Raise()

    def on_pick(sender, args):
        start_pick("pick")
    find("PickButton").Click += on_pick

    def on_box_select(sender, args):
        start_pick("box")
    find("BoxSelectButton").Click += on_box_select

    add_handler = AddFromListHandler(list_box, status_text)
    add_event = ExternalEvent.Create(add_handler)

    def on_from_list(sender, args):
        def add_chosen(chosen):
            add_handler.entries = chosen
            add_event.Raise()

        show_room_list_window(add_chosen, status_text, selected_source_key())
    find("FromListButton").Click += on_from_list

    def on_diagnose(sender, args):
        try:
            lines = core.diagnose_rooms(doc, doc.ActiveView, selected_source_key())
        except Exception:
            lines = ["Diagnosis failed:", traceback.format_exc()]
        show_report_window(lines)
    find("DiagnoseButton").Click += on_diagnose

    def on_remove(sender, args):
        # WPF ListBox exposes SelectedItems, not SelectedIndices.
        selected_items = list(list_box.SelectedItems)
        indices = []
        for item in selected_items:
            idx = list_box.Items.IndexOf(item)
            if idx >= 0:
                indices.append(idx)
        indices.sort(reverse=True)

        for idx in indices:
            list_box.Items.RemoveAt(idx)
            del picked_rooms[idx]
        status_text.Text = str(len(picked_rooms)) + " room(s) picked."
    find("RemoveButton").Click += on_remove

    def on_delete_lines(sender, args):
        run_handler.mode = "delete_lines"
        status_text.Text = "Deleting separation lines..."
        run_event.Raise()
    find("DeleteLinesButton").Click += on_delete_lines

    def on_clear(sender, args):
        list_box.Items.Clear()
        del picked_rooms[:]
        status_text.Text = "List cleared."
    find("ClearButton").Click += on_clear

    def current_mode():
        try:
            index = tabs.SelectedIndex
        except Exception:
            index = 0
        if index == 1:
            return "manual"
        if index == 2:
            return "manage"
        return "auto"

    manage_loaded = [False]

    def on_tab_changed(sender, args):
        mode = current_mode()
        if mode == "manual":
            action_button.Content = "Create Spaces"
            status_text.Text = "Select Rooms: click rooms, Tab cycles stacked ones, then Finish."
        elif mode == "manage":
            action_button.Content = "Apply"
            status_text.Text = ("Edit Base / Limit offsets in the grid, or Push "
                                "Spaces Up To Floor. Nothing is written until Apply.")
            if not manage_loaded[0]:
                manage_loaded[0] = True
                try:
                    manage_grid.load()
                except Exception:
                    logger.error(traceback.format_exc())
        else:
            action_button.Content = "Place Spaces"
            status_text.Text = ""
    tabs.SelectionChanged += on_tab_changed

    def on_action(sender, args):
        mode = current_mode()
        if mode == "manage":
            if not manage_grid.pending_rows():
                status_text.Text = "Nothing pending to apply."
                return
            run_handler.mode = "manage_apply"
            status_text.Text = "Applying..."
            run_event.Raise()
            return
        options = Options(window, resolve_selected_workset)
        options.save()
        run_handler.mode = mode
        run_handler.options = options
        status_text.Text = "Working..."
        run_event.Raise()
    action_button.Click += on_action

    # --- manage tab buttons --------------------------------------------
    push_event = ExternalEvent.Create(PushUpHandler(manage_grid, status_text))

    def on_push_up(sender, args):
        push_event.Raise()
    find("PushUpButton").Click += on_push_up

    def on_manage_refresh(sender, args):
        if manage_grid.pending_rows():
            status_text.Text = ("Refresh discards pending edits - press "
                                "Discard Pending first if that is intended.")
            return
        manage_grid.load()
        status_text.Text = "Space list refreshed."
    find("ManageRefreshButton").Click += on_manage_refresh

    def on_manage_discard(sender, args):
        manage_grid.discard()
        status_text.Text = "Pending edits discarded."
    find("ManageDiscardButton").Click += on_manage_discard

    # --- debug panel ---------------------------------------------------
    debug_panel = find("DebugPanel")
    debug_text = find("DebugText")
    debug_toggle = find("DebugToggleButton")
    debug_lines = []

    def debug_sink(line):
        """Receives every log line core writes. Runs on Revit's thread,
        which is the same thread the window was created on, so the text
        box can be written to directly."""
        debug_lines.append(line)
        if len(debug_lines) > 400:
            del debug_lines[0:len(debug_lines) - 400]
        try:
            debug_text.Text = "\n".join(debug_lines)
            debug_text.ScrollToEnd()
        except Exception:
            pass

    core.clear_log_sinks()
    core.add_log_sink(debug_sink)

    def on_debug_toggle(sender, args):
        if debug_panel.Visibility == Visibility.Visible:
            debug_panel.Visibility = Visibility.Collapsed
            debug_toggle.Content = "+  Debug log"
        else:
            debug_panel.Visibility = Visibility.Visible
            debug_toggle.Content = "-  Debug log"
            try:
                debug_text.ScrollToEnd()
            except Exception:
                pass
    debug_toggle.Click += on_debug_toggle

    def on_debug_select(sender, args):
        try:
            debug_text.Focus()
            debug_text.SelectAll()
        except Exception:
            pass
    find("DebugSelectButton").Click += on_debug_select

    def on_debug_clear(sender, args):
        del debug_lines[:]
        debug_text.Text = ""
    find("DebugClearButton").Click += on_debug_clear

    core.log_pick("window opened, version " + __version__)

    saved = core.load_settings()
    if saved.get("scope") == "all_project":
        find("ScopeAllProject").IsChecked = True
    source = saved.get("room_source", "both")
    if source == "host":
        find("SourceHost").IsChecked = True
    elif source == "links":
        find("SourceLinks").IsChecked = True
    find("ChkSeparationLines").IsChecked = saved.get("create_separation_lines", "1") == "1"
    find("ChkClearExisting").IsChecked = saved.get("clear_existing", "0") == "1"
    find("ChkInheritName").IsChecked = saved.get("inherit_room_name", "1") == "1"
    find("ChkPushCeiling").IsChecked = saved.get("push_to_ceiling", "0") == "1"
    if saved.get("boundary_mode", "lines") == "native":
        find("BoundaryNative").IsChecked = True

    window.Show()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        logger.error(tb)
        try:
            TaskDialog.Show("RevoBIM Space Creator - error", tb)
        except Exception:
            print(tb)
