# -*- coding: utf-8 -*-
"""RevoBIM PY | Family Management Placer

Places every selected family / type into tidy per-category columns in the active
floor plan or drafting view, tags them with Multi-Category tags and drops a 3D
text heading above each column.  Built for review / QA sheets.
"""

# ---------------------------------------------------------------------------
#  Metadata
# ---------------------------------------------------------------------------
__title__ = "Family Management Placer"
__author__ = "RevoBIM PY"
__doc__ = ("Place project families in per-category columns with tags and 3D "
           "text headings for review.")
__persistentengine__ = True

TOOL_NAME = "Family Management Placer"
TOOL_VERSION = "1.10.0"
TOOL_KEY = "family_management_placer"

# ---------------------------------------------------------------------------
#  Imports  (pyRevit first, then CLR references, then System.Windows)
# ---------------------------------------------------------------------------
from pyrevit import revit, DB, UI                                    # noqa

import clr
clr.AddReference('PresentationCore')
clr.AddReference('PresentationFramework')
clr.AddReference('WindowsBase')
clr.AddReference('System.Xml')

import os
import json
import traceback

from System import AppDomain
from System.IO import StringReader
from System.Xml import XmlReader
from System.Windows import (Window, Thickness, Visibility, TextTrimming,
                            TextWrapping, TextAlignment, FontWeights,
                            HorizontalAlignment, VerticalAlignment)
from System.Windows.Controls import (StackPanel, Border, CheckBox, TextBlock,
                                     Orientation, ComboBoxItem)
from System.Windows.Markup import XamlReader
from System.Windows.Media import Color, SolidColorBrush, Brushes
from System.Windows.Input import Cursors
from System.Windows.Interop import WindowInteropHelper

from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Autodesk.Revit.Exceptions import OperationCanceledException

# ---------------------------------------------------------------------------
#  Theme  (RevoBIM PY design system)
# ---------------------------------------------------------------------------
CLR_SHELL = '#262A31'
CLR_PANEL = '#2F343C'
CLR_FIELD = '#21252B'
CLR_TITLE = '#2B2B2B'
CLR_BORDER = '#4F4F4F'
CLR_TEXT = '#DCDCDC'
CLR_MUTED = '#9AA0A6'
CLR_BLUE = '#3D9BE9'
CLR_ORANGE = '#F07C10'

MM = 1.0 / 304.8                      # millimetres -> internal feet
GLYPH_CLOSED = u'\u25B6'
GLYPH_OPEN = u'\u25BC'

DOMAIN_KEY = 'RevoBIM_PY_FamilyManagementPlacer_v1'

# Tag offsets are quoted at 1:1 in the UI and stored here at 1:100, so
# 10 mm at 1:1 is 1000 mm at 1:100 and 20 mm at 1:1 is 2000 mm.
TAG_V_AT_1TO1 = 10.0
TAG_H_AT_1TO1 = 20.0
# Heading offset is quoted at 1:50, so 1500 mm there is 3000 mm at 1:100.
HEAD_AT_1TO50 = 1500.0

DEFAULTS = {
    'family_tag_offset': TAG_V_AT_1TO1 * 100.0,
    'type_tag_offset': TAG_H_AT_1TO1 * 100.0,
    'family_spacing': 1000.0,
    'column_spacing': 10000.0,
    'group_gap': 100.0,
    'workset_name': 'Family Container',
    'family_tag': '',
    'type_tag': '',
    'do_tagging': True,
    'show_headings': True,
    'show_results': False,
    'keep_open': False,
    'heading_offset': HEAD_AT_1TO50 * 2.0,
    'heading_style': '',
    'scale': 100.0,
}

# every distance setting below is authored at 1:100 and rescaled by the
# scale box; group gap is a percentage and text depth is a type property,
# so neither is scaled.
SCALED_KEYS = ('family_tag_offset', 'type_tag_offset', 'family_spacing',
               'column_spacing', 'heading_offset')

# choices that persist between sessions; the scaled distances above always
# restart from the defaults and follow the active view's own scale.
REMEMBERED_KEYS = ('workset_name', 'family_tag', 'type_tag', 'do_tagging',
                   'show_headings', 'heading_style', 'group_gap',
                   'show_results', 'keep_open')

SCALE_STEPS = ((u'1:100', 100.0), (u'1:50', 50.0), (u'1:25', 25.0),
               (u'1:10', 10.0), (u'1:1', 1.0))


# ---------------------------------------------------------------------------
#  Small helpers
# ---------------------------------------------------------------------------
def brush(hex_str):
    h = hex_str.lstrip('#')
    return SolidColorBrush(Color.FromRgb(int(h[0:2], 16),
                                         int(h[2:4], 16),
                                         int(h[4:6], 16)))


def eid_val(eid):
    """ElementId -> int, tolerant of the 2024 Value / IntegerValue change."""
    try:
        return int(eid.Value)
    except Exception:
        return int(eid.IntegerValue)


def bic_id(bic):
    return eid_val(DB.ElementId(bic))


def elem_name(elem):
    """Element name, resilient to IronPython property-hiding on Element.Name."""
    try:
        return DB.Element.Name.GetValue(elem)
    except Exception:
        pass
    try:
        return elem.Name
    except Exception:
        return u'<unnamed>'


def type_name(symbol):
    par = symbol.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
    if par is not None:
        val = par.AsString()
        if val:
            return val
    return elem_name(symbol)


def fpt(name):
    """Safe lookup of a FamilyPlacementType member."""
    return getattr(DB.FamilyPlacementType, name, None)


def settings_path():
    folder = os.path.join(os.getenv('APPDATA'), 'RevoBIM PY')
    if not os.path.isdir(folder):
        try:
            os.makedirs(folder)
        except Exception:
            pass
    return os.path.join(folder, TOOL_KEY + '_settings.json')


def load_settings():
    data = dict(DEFAULTS)
    try:
        p = settings_path()
        if os.path.isfile(p):
            with open(p, 'r') as f:
                stored = json.load(f)
            for k in REMEMBERED_KEYS:
                if k in stored:
                    data[k] = stored[k]
    except Exception:
        pass
    return data


def save_settings(data):
    try:
        out = dict(data)
        out['_tool'] = TOOL_NAME
        out['_version'] = TOOL_VERSION
        with open(settings_path(), 'w') as f:
            json.dump(out, f, indent=2)
    except Exception:
        pass


def fmt_num(value):
    """Tidy number for a text box - 1000.0 -> '1000', 12.5 -> '12.5'."""
    try:
        v = float(value)
    except Exception:
        return str(value)
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    return ('%.3f' % v).rstrip('0').rstrip('.')


def to_float(text, fallback, minimum=1.0):
    try:
        v = float(str(text).strip())
        if v < minimum:
            return minimum
        return v
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
#  Shared XAML fragments
# ---------------------------------------------------------------------------
STYLES = u"""
  <Style TargetType="TextBlock">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="VerticalAlignment" Value="Center"/>
  </Style>

  <Style x:Key="Cap" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#9AA0A6"/>
    <Setter Property="FontSize" Value="11"/>
    <Setter Property="Margin" Value="0,0,0,3"/>
  </Style>

  <Style x:Key="Sec" TargetType="TextBlock">
    <Setter Property="Foreground" Value="#3D9BE9"/>
    <Setter Property="FontSize" Value="11"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Margin" Value="0,0,0,6"/>
  </Style>

  <Style TargetType="CheckBox">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="VerticalContentAlignment" Value="Center"/>
  </Style>

  <Style x:Key="Fld" TargetType="TextBox">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="CaretBrush" Value="#DCDCDC"/>
    <Setter Property="Background" Value="#21252B"/>
    <Setter Property="BorderBrush" Value="#4F4F4F"/>
    <Setter Property="BorderThickness" Value="1"/>
    <Setter Property="Padding" Value="6,4"/>
    <Setter Property="Height" Value="26"/>
    <Setter Property="VerticalContentAlignment" Value="Center"/>
  </Style>

  <Style x:Key="Btn" TargetType="Button">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="Background" Value="#2F343C"/>
    <Setter Property="BorderBrush" Value="#4F4F4F"/>
    <Setter Property="Padding" Value="10,5"/>
    <Setter Property="FontSize" Value="12"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="B" Background="{TemplateBinding Background}"
                  BorderBrush="{TemplateBinding BorderBrush}"
                  BorderThickness="1" CornerRadius="2">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              Margin="{TemplateBinding Padding}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="Background" Value="#3A4048"/>
              <Setter TargetName="B" Property="BorderBrush" Value="#3D9BE9"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="BtnGo" TargetType="Button">
    <Setter Property="Foreground" Value="#FFFFFF"/>
    <Setter Property="Background" Value="#3D9BE9"/>
    <Setter Property="Padding" Value="18,6"/>
    <Setter Property="FontWeight" Value="SemiBold"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="B" Background="{TemplateBinding Background}"
                  BorderBrush="#3D9BE9" BorderThickness="1" CornerRadius="2">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"
                              Margin="{TemplateBinding Padding}"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="Background" Value="#5AAEF0"/>
            </Trigger>
            <Trigger Property="IsEnabled" Value="False">
              <Setter Property="Opacity" Value="0.4"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="BtnGear" TargetType="Button">
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Width" Value="34"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="B" Background="{TemplateBinding Background}">
            <Grid Width="20" Height="20" HorizontalAlignment="Center" VerticalAlignment="Center">
              <Path x:Name="G" Fill="#9AA0A6" Stretch="Uniform" Margin="1"
                    Data="M 9.1,1 L 10.9,1 L 11.3,3.1 C 11.9,3.3 12.5,3.6 13,4 L 15,3.2 L 15.9,4.8 L 14.3,6.2 C 14.4,6.5 14.4,6.8 14.4,7.1 C 14.4,7.4 14.4,7.7 14.3,8 L 15.9,9.4 L 15,11 L 13,10.2 C 12.5,10.6 11.9,10.9 11.3,11.1 L 10.9,13.2 L 9.1,13.2 L 8.7,11.1 C 8.1,10.9 7.5,10.6 7,10.2 L 5,11 L 4.1,9.4 L 5.7,8 C 5.6,7.7 5.6,7.4 5.6,7.1 C 5.6,6.8 5.6,6.5 5.7,6.2 L 4.1,4.8 L 5,3.2 L 7,4 C 7.5,3.6 8.1,3.3 8.7,3.1 Z M 10,5.3 C 9,5.3 8.2,6.1 8.2,7.1 C 8.2,8.1 9,8.9 10,8.9 C 11,8.9 11.8,8.1 11.8,7.1 C 11.8,6.1 11,5.3 10,5.3 Z"/>
            </Grid>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="Background" Value="#3A4048"/>
              <Setter TargetName="G" Property="Fill" Value="#3D9BE9"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="BtnX" TargetType="Button">
    <Setter Property="Foreground" Value="#9AA0A6"/>
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Width" Value="34"/>
    <Setter Property="FontSize" Value="13"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Button">
          <Border x:Name="B" Background="{TemplateBinding Background}">
            <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsMouseOver" Value="True">
              <Setter TargetName="B" Property="Background" Value="#C0392B"/>
              <Setter Property="Foreground" Value="#FFFFFF"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="SbThumb" TargetType="Thumb">
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="Thumb">
          <Border Background="#4F4F4F" CornerRadius="3" Margin="2"/>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ScrollBar">
    <Setter Property="Background" Value="#262A31"/>
    <Setter Property="Width" Value="10"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ScrollBar">
          <Grid Background="{TemplateBinding Background}">
            <Track x:Name="PART_Track" IsDirectionReversed="True">
              <Track.DecreaseRepeatButton>
                <RepeatButton Command="ScrollBar.PageUpCommand" Opacity="0" Focusable="False"/>
              </Track.DecreaseRepeatButton>
              <Track.Thumb>
                <Thumb Style="{StaticResource SbThumb}"/>
              </Track.Thumb>
              <Track.IncreaseRepeatButton>
                <RepeatButton Command="ScrollBar.PageDownCommand" Opacity="0" Focusable="False"/>
              </Track.IncreaseRepeatButton>
            </Track>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style x:Key="Combo" TargetType="ComboBox">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="Height" Value="26"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBox">
          <Grid TextBlock.Foreground="#DCDCDC">
            <ToggleButton x:Name="Toggle" Focusable="False" ClickMode="Press"
                          IsChecked="{Binding IsDropDownOpen, Mode=TwoWay,
                                      RelativeSource={RelativeSource TemplatedParent}}">
              <ToggleButton.Template>
                <ControlTemplate TargetType="ToggleButton">
                  <Border x:Name="TB" Background="#21252B" BorderBrush="#4F4F4F"
                          BorderThickness="1" CornerRadius="2">
                    <Path HorizontalAlignment="Right" VerticalAlignment="Center"
                          Margin="0,0,8,0" Data="M0,0 L8,0 L4,5 Z" Fill="#9AA0A6"/>
                  </Border>
                  <ControlTemplate.Triggers>
                    <Trigger Property="IsMouseOver" Value="True">
                      <Setter TargetName="TB" Property="BorderBrush" Value="#3D9BE9"/>
                    </Trigger>
                  </ControlTemplate.Triggers>
                </ControlTemplate>
              </ToggleButton.Template>
            </ToggleButton>
            <ContentPresenter IsHitTestVisible="False"
                              Content="{TemplateBinding SelectionBoxItem}"
                              ContentTemplate="{TemplateBinding SelectionBoxItemTemplate}"
                              Margin="8,0,26,0" VerticalAlignment="Center"/>
            <Popup x:Name="PART_Popup" AllowsTransparency="True" Placement="Bottom"
                   IsOpen="{TemplateBinding IsDropDownOpen}" Focusable="False">
              <Border Background="#2B2B2B" BorderBrush="#4F4F4F" BorderThickness="1"
                      MinWidth="{TemplateBinding ActualWidth}" MaxHeight="260">
                <ScrollViewer VerticalScrollBarVisibility="Auto">
                  <StackPanel IsItemsHost="True"/>
                </ScrollViewer>
              </Border>
            </Popup>
          </Grid>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>

  <Style TargetType="ComboBoxItem">
    <Setter Property="Foreground" Value="#DCDCDC"/>
    <Setter Property="Background" Value="Transparent"/>
    <Setter Property="Padding" Value="8,5"/>
    <Setter Property="Template">
      <Setter.Value>
        <ControlTemplate TargetType="ComboBoxItem">
          <Border x:Name="B" Background="{TemplateBinding Background}"
                  Padding="{TemplateBinding Padding}">
            <ContentPresenter/>
          </Border>
          <ControlTemplate.Triggers>
            <Trigger Property="IsHighlighted" Value="True">
              <Setter TargetName="B" Property="Background" Value="#3D9BE9"/>
            </Trigger>
          </ControlTemplate.Triggers>
        </ControlTemplate>
      </Setter.Value>
    </Setter>
  </Style>
"""


MAIN_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY - Family Management Placer"
        Height="660" Width="700" MinHeight="540" MinWidth="560"
        WindowStartupLocation="CenterScreen" WindowStyle="None"
        ResizeMode="CanResize" ShowInTaskbar="True"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12">
  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" ResizeBorderThickness="6"
                        GlassFrameThickness="0" CornerRadius="0"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
__STYLES__
  </Window.Resources>

  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <!-- ============ title bar ============ -->
      <Border x:Name="titleBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0" Orientation="Horizontal" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text="  |  Family Management Placer" Foreground="#DCDCDC" FontSize="13"/>
          </StackPanel>
          <TextBlock x:Name="verLabel" Grid.Column="1" Text="v0.0.0" Foreground="#9AA0A6"
                     FontSize="11" Margin="0,0,8,0"/>
          <Button x:Name="btnSettings" Grid.Column="2" Style="{StaticResource BtnGear}"
                  ToolTip="Settings"/>
          <Button x:Name="btnClose" Grid.Column="3" Style="{StaticResource BtnX}" Content="&#x2715;"/>
        </Grid>
      </Border>

      <!-- ============ body ============ -->
      <Border Grid.Row="1" Margin="12,10,12,4" Background="#2F343C"
              BorderBrush="#4F4F4F" BorderThickness="1">
        <Grid>
          <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
          </Grid.RowDefinitions>

          <StackPanel Grid.Row="0" Margin="10,10,10,6">
            <TextBlock Style="{StaticResource Sec}" Text="PROJECT FAMILIES"/>
            <TextBlock x:Name="scopeLabel" Foreground="#9AA0A6" FontSize="11"
                       TextWrapping="Wrap" Text="-"/>
            <TextBlock x:Name="cfgLabel" Foreground="#9AA0A6" FontSize="11"
                       TextWrapping="Wrap" Margin="0,4,0,0" Text="-"/>
          </StackPanel>

          <Grid Grid.Row="1" Margin="10,0,10,8">
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="Auto"/>
            </Grid.ColumnDefinitions>
            <TextBox x:Name="txtFilter" Grid.Column="0" Style="{StaticResource Fld}"/>
            <Button x:Name="btnReload" Grid.Column="1" Style="{StaticResource Btn}"
                    Content="Reload" Margin="6,0,0,0"/>
          </Grid>

          <Border Grid.Row="2" Background="#21252B" BorderBrush="#4F4F4F"
                  BorderThickness="1" Margin="10,0,10,8">
            <ScrollViewer x:Name="scroller" VerticalScrollBarVisibility="Auto"
                          HorizontalScrollBarVisibility="Disabled" Padding="4">
              <StackPanel x:Name="rowsPanel"/>
            </ScrollViewer>
          </Border>

          <StackPanel Grid.Row="3" Orientation="Horizontal" Margin="10,0,10,10">
            <Button x:Name="btnAll" Style="{StaticResource Btn}" Content="Select all"/>
            <Button x:Name="btnNone" Style="{StaticResource Btn}" Content="Clear" Margin="6,0,0,0"/>
            <Button x:Name="btnExpand" Style="{StaticResource Btn}" Content="Expand" Margin="6,0,0,0"/>
            <Button x:Name="btnCollapse" Style="{StaticResource Btn}" Content="Collapse" Margin="6,0,0,0"/>
          </StackPanel>
        </Grid>
      </Border>

      <!-- ============ footer ============ -->
      <Border Grid.Row="2" Background="#21252B" BorderBrush="#4F4F4F" BorderThickness="0,1,0,0">
        <Grid Margin="14,10,12,10">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBlock x:Name="statusLabel" Grid.Column="0" Foreground="#9AA0A6"
                     TextTrimming="CharacterEllipsis" Text="Ready."/>
          <StackPanel Grid.Column="1" Orientation="Horizontal">
            <Button x:Name="btnCancel" Style="{StaticResource Btn}" Content="Close"/>
            <Button x:Name="btnRun" Style="{StaticResource BtnGo}" Content="Run" Margin="8,0,0,0"/>
          </StackPanel>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


DIALOG_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY" SizeToContent="Height" Width="480" MaxHeight="620"
        WindowStartupLocation="CenterScreen" WindowStyle="None"
        ResizeMode="NoResize" ShowInTaskbar="False"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12">
  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" ResizeBorderThickness="0"
                        GlassFrameThickness="0" CornerRadius="0"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
__STYLES__
  </Window.Resources>

  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <Border x:Name="titleBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0" Orientation="Horizontal" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock x:Name="dlgTitle" Text="  |  " Foreground="#DCDCDC" FontSize="13"/>
          </StackPanel>
          <TextBlock x:Name="verLabel" Grid.Column="1" Text="v0.0.0" Foreground="#9AA0A6"
                     FontSize="11" Margin="0,0,10,0"/>
          <Button x:Name="btnClose" Grid.Column="2" Style="{StaticResource BtnX}" Content="&#x2715;"/>
        </Grid>
      </Border>

      <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto"
                    HorizontalScrollBarVisibility="Disabled" MaxHeight="470">
        <StackPanel x:Name="dlgBody" Margin="18,16,18,10"/>
      </ScrollViewer>

      <Border Grid.Row="2" Background="#21252B" BorderBrush="#4F4F4F" BorderThickness="0,1,0,0">
        <Grid Margin="14,10,12,10">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <TextBlock x:Name="dlgFoot" Grid.Column="0" Foreground="#9AA0A6" FontSize="11" Text=""/>
          <Button x:Name="btnOk" Grid.Column="1" Style="{StaticResource BtnGo}" Content="OK"/>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


SETTINGS_XAML = u"""
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        xmlns:shell="clr-namespace:System.Windows.Shell;assembly=PresentationFramework"
        Title="RevoBIM PY - Settings"
        Height="700" Width="440" MinHeight="480" MinWidth="400"
        WindowStartupLocation="CenterOwner" WindowStyle="None"
        ResizeMode="CanResize" ShowInTaskbar="False"
        Background="#262A31" FontFamily="Segoe UI" FontSize="12">
  <shell:WindowChrome.WindowChrome>
    <shell:WindowChrome CaptionHeight="0" ResizeBorderThickness="6"
                        GlassFrameThickness="0" CornerRadius="0"/>
  </shell:WindowChrome.WindowChrome>

  <Window.Resources>
__STYLES__
  </Window.Resources>

  <Border BorderBrush="#4F4F4F" BorderThickness="1">
    <Grid>
      <Grid.RowDefinitions>
        <RowDefinition Height="38"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <Border x:Name="titleBar" Grid.Row="0" Background="#2B2B2B">
        <Grid>
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <StackPanel Grid.Column="0" Orientation="Horizontal" Margin="14,0,0,0">
            <TextBlock Text="RevoBIM" Foreground="#3D9BE9" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text=" PY" Foreground="#F07C10" FontSize="14" FontWeight="Bold"/>
            <TextBlock Text="  |  Settings" Foreground="#DCDCDC" FontSize="13"/>
          </StackPanel>
          <TextBlock x:Name="verLabel" Grid.Column="1" Text="v0.0.0" Foreground="#9AA0A6"
                     FontSize="11" Margin="0,0,10,0"/>
          <Button x:Name="btnClose" Grid.Column="2" Style="{StaticResource BtnX}" Content="&#x2715;"/>
        </Grid>
      </Border>

      <ScrollViewer Grid.Row="1" VerticalScrollBarVisibility="Auto"
                    HorizontalScrollBarVisibility="Disabled">
        <StackPanel Margin="16,12,16,14">

          <TextBlock Style="{StaticResource Sec}" Text="VIEW SCALE"/>
          <ComboBox x:Name="cboScale" Style="{StaticResource Combo}"/>
          <TextBlock x:Name="scaleLabel" Foreground="#9AA0A6" FontSize="10"
                     TextWrapping="Wrap" Margin="0,6,0,0" Text="-"/>
          <TextBlock Foreground="#9AA0A6" FontSize="10" TextWrapping="Wrap" Margin="0,6,0,0"
                     Text="Set from the active view on open. Changing it rescales every distance below."/>

          <Border Height="1" Background="#4F4F4F" Margin="0,16,0,14"/>
          <TextBlock Style="{StaticResource Sec}" Text="LAYOUT"/>

          <TextBlock Style="{StaticResource Cap}" Text="Family vertical spacing (mm)"/>
          <TextBox x:Name="txtVert" Style="{StaticResource Fld}"/>

          <TextBlock Style="{StaticResource Cap}" Text="Category column spacing (mm)" Margin="0,10,0,3"/>
          <TextBox x:Name="txtCol" Style="{StaticResource Fld}"/>

          <TextBlock Style="{StaticResource Cap}" Text="Family group gap (% of vertical spacing)" Margin="0,10,0,3"/>
          <TextBox x:Name="txtGap" Style="{StaticResource Fld}"/>
          <TextBlock Foreground="#9AA0A6" FontSize="10" TextWrapping="Wrap" Margin="0,6,0,0"
                     Text="Types of the same family stay together as a group. Each new family group in a column drops by this extra percentage, leaving room for the family tag above it."/>

          <Border Height="1" Background="#4F4F4F" Margin="0,16,0,14"/>
          <TextBlock Style="{StaticResource Sec}" Text="TAGGING"/>

          <CheckBox x:Name="chkTag" Content="Tag placed families" Margin="0,0,0,10"/>

          <TextBlock Style="{StaticResource Cap}" Text="Multi-category tag - family name"/>
          <ComboBox x:Name="cboFamTag" Style="{StaticResource Combo}"/>

          <TextBlock Style="{StaticResource Cap}" Text="Family tag vertical offset (mm)" Margin="0,10,0,3"/>
          <TextBox x:Name="txtFamOff" Style="{StaticResource Fld}"/>
          <TextBlock x:Name="famOffLabel" Foreground="#9AA0A6" FontSize="10" Margin="0,4,0,0" Text="-"/>

          <TextBlock Style="{StaticResource Cap}" Text="Multi-category tag - type name" Margin="0,12,0,3"/>
          <ComboBox x:Name="cboTypeTag" Style="{StaticResource Combo}"/>

          <TextBlock Style="{StaticResource Cap}" Text="Type tag horizontal offset (mm)" Margin="0,10,0,3"/>
          <TextBox x:Name="txtTypeOff" Style="{StaticResource Fld}"/>
          <TextBlock x:Name="typeOffLabel" Foreground="#9AA0A6" FontSize="10" Margin="0,4,0,0" Text="-"/>

          <TextBlock Foreground="#9AA0A6" FontSize="10" TextWrapping="Wrap" Margin="0,8,0,0"
                     Text="Family tag sits above the first type of each family group. Type tag sits right of every instance."/>

          <Border Height="1" Background="#4F4F4F" Margin="0,16,0,14"/>
          <TextBlock Style="{StaticResource Sec}" Text="HEADINGS"/>

          <CheckBox x:Name="chkHead" Content="Place a heading above each column" Margin="0,0,0,10"/>

          <TextBlock Style="{StaticResource Cap}" Text="Text style"/>
          <ComboBox x:Name="cboHeadStyle" Style="{StaticResource Combo}"/>
          <TextBlock x:Name="headStyleLabel" Foreground="#9AA0A6" FontSize="10"
                     TextWrapping="Wrap" Margin="0,4,0,0" Text="-"/>

          <TextBlock Style="{StaticResource Cap}" Text="Heading height above first placement (mm)" Margin="0,10,0,3"/>
          <TextBox x:Name="txtHeadOff" Style="{StaticResource Fld}"/>
          <TextBlock x:Name="headOffLabel" Foreground="#9AA0A6" FontSize="10" Margin="0,4,0,0" Text="-"/>

          <TextBlock Foreground="#9AA0A6" FontSize="10" TextWrapping="Wrap" Margin="0,8,0,0"
                     Text="The category name is placed as a text note in the chosen style. Text size comes from the style itself; the height above is a model distance and scales with the view."/>

          <Border Height="1" Background="#4F4F4F" Margin="0,16,0,14"/>
          <TextBlock Style="{StaticResource Sec}" Text="AFTER PLACEMENT"/>

          <CheckBox x:Name="chkResults" Content="Show the results summary" Margin="0,0,0,8"/>
          <CheckBox x:Name="chkKeepOpen" Content="Keep the tool open after placing"/>
          <TextBlock Foreground="#9AA0A6" FontSize="10" TextWrapping="Wrap" Margin="0,8,0,0"
                     Text="Both off by default: the tool places, closes and gets out of the way. A failure is always reported and always leaves the tool open, whatever these say."/>

          <Border Height="1" Background="#4F4F4F" Margin="0,16,0,14"/>
          <TextBlock Style="{StaticResource Sec}" Text="WORKSET"/>

          <TextBlock Style="{StaticResource Cap}" Text="Target workset"/>
          <ComboBox x:Name="cboWorkset" Style="{StaticResource Combo}"/>
          <TextBlock x:Name="wsLabel" Foreground="#9AA0A6" FontSize="10"
                     TextWrapping="Wrap" Margin="0,6,0,0" Text="-"/>
        </StackPanel>
      </ScrollViewer>

      <Border Grid.Row="2" Background="#21252B" BorderBrush="#4F4F4F" BorderThickness="0,1,0,0">
        <Grid Margin="14,10,12,10">
          <Grid.ColumnDefinitions>
            <ColumnDefinition Width="Auto"/>
            <ColumnDefinition Width="*"/>
            <ColumnDefinition Width="Auto"/>
          </Grid.ColumnDefinitions>
          <Button x:Name="btnReset" Grid.Column="0" Style="{StaticResource Btn}"
                  Content="Reset defaults"/>
          <StackPanel Grid.Column="2" Orientation="Horizontal">
            <Button x:Name="btnCancel" Style="{StaticResource Btn}" Content="Cancel"/>
            <Button x:Name="btnSave" Style="{StaticResource BtnGo}" Content="Save" Margin="8,0,0,0"/>
          </StackPanel>
        </Grid>
      </Border>
    </Grid>
  </Border>
</Window>
"""


def load_xaml(xaml):
    return XamlReader.Load(XmlReader.Create(StringReader(
        xaml.replace(u'__STYLES__', STYLES))))


def own_to_revit(win):
    try:
        WindowInteropHelper(win).Owner = __revit__.MainWindowHandle
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  Themed dialog
# ---------------------------------------------------------------------------
def themed_dialog(title, lines, footer='', rows=None):
    """lines -> list of (text, kind) with kind in head/body/muted/warn.
       rows  -> list of (label, value_a, value_b) rendered as a table."""
    win = load_xaml(DIALOG_XAML)
    win.FindName('dlgTitle').Text = u'  |  ' + title
    win.FindName('verLabel').Text = u'v' + TOOL_VERSION
    win.FindName('dlgFoot').Text = footer
    body = win.FindName('dlgBody')

    for text, kind in (lines or []):
        tb = TextBlock()
        tb.Text = text
        tb.TextWrapping = TextWrapping.Wrap
        tb.Margin = Thickness(0, 0, 0, 8)
        if kind == 'head':
            tb.Foreground = brush(CLR_TEXT)
            tb.FontSize = 14
            tb.FontWeight = FontWeights.Bold
        elif kind == 'muted':
            tb.Foreground = brush(CLR_MUTED)
            tb.FontSize = 11
        elif kind == 'warn':
            tb.Foreground = brush(CLR_ORANGE)
        else:
            tb.Foreground = brush(CLR_TEXT)
        body.Children.Add(tb)

    if rows:
        head = _table_row(u'CATEGORY', u'PLACED', u'SKIPPED', header=True)
        body.Children.Add(head)
        for label, a, b in rows:
            body.Children.Add(_table_row(label, a, b))

    win.FindName('btnOk').Click += lambda s, e: win.Close()
    win.FindName('btnClose').Click += lambda s, e: win.Close()
    win.FindName('titleBar').MouseLeftButtonDown += lambda s, e: win.DragMove()
    own_to_revit(win)
    win.ShowDialog()


def _table_row(label, val_a, val_b, header=False):
    border = Border()
    border.BorderBrush = brush(CLR_BORDER)
    border.BorderThickness = Thickness(0, 0, 0, 1)
    border.Padding = Thickness(0, 5, 0, 5)

    sp = StackPanel()
    sp.Orientation = Orientation.Horizontal

    t1 = TextBlock()
    t1.Text = u'{0}'.format(label)
    t1.Width = 300
    t1.TextTrimming = TextTrimming.CharacterEllipsis
    t1.Foreground = brush(CLR_MUTED if header else CLR_TEXT)
    t1.FontSize = 11 if header else 12

    t2 = TextBlock()
    t2.Text = str(val_a)
    t2.Width = 70
    t2.TextAlignment = TextAlignment.Right
    t2.Foreground = brush(CLR_MUTED if header else CLR_BLUE)
    t2.FontSize = 11 if header else 12

    t3 = TextBlock()
    t3.Text = str(val_b)
    t3.Width = 70
    t3.TextAlignment = TextAlignment.Right
    t3.Foreground = brush(CLR_MUTED if header else CLR_ORANGE)
    t3.FontSize = 11 if header else 12

    sp.Children.Add(t1)
    sp.Children.Add(t2)
    sp.Children.Add(t3)
    border.Child = sp
    return border


# ---------------------------------------------------------------------------
#  View helpers
# ---------------------------------------------------------------------------
PLAN_TYPES = ('FloorPlan', 'CeilingPlan', 'EngineeringPlan', 'AreaPlan')


def view_kind(view):
    if view is None:
        return None
    try:
        if isinstance(view, DB.ViewDrafting):
            return 'drafting'
        if isinstance(view, DB.ViewPlan):
            if str(view.ViewType) in PLAN_TYPES:
                return 'plan'
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
#  Family harvesting
# ---------------------------------------------------------------------------
def _excluded_bics():
    names = ['OST_TitleBlocks', 'OST_ProfileFamilies', 'OST_CurtainWallPanels',
             'OST_Mass', 'OST_StackedWalls', 'OST_MultiCategoryTags',
             'OST_Coupler', 'OST_RvtLinks']
    out = set()
    for n in names:
        bic = getattr(DB.BuiltInCategory, n, None)
        if bic is not None:
            try:
                out.add(bic_id(bic))
            except Exception:
                pass
    return out


def family_allowed(fam, kind, excluded):
    """Decide whether a family should be offered for the active view kind."""
    try:
        if fam.IsInPlace:
            return False
    except Exception:
        pass

    cat = fam.FamilyCategory
    if cat is None:
        return False
    try:
        if bic_id(cat.Id) in excluded:
            return False
    except Exception:
        pass

    # drop every tag family - tags need a host element, not a placement point
    try:
        if cat.CategoryType == DB.CategoryType.Annotation and \
                cat.Name.strip().lower().endswith('tags'):
            return False
    except Exception:
        pass

    placement = None
    try:
        placement = fam.FamilyPlacementType
    except Exception:
        pass

    view_based = [p for p in (fpt('ViewBased'), fpt('CurveBasedDetail')) if p]
    if kind == 'drafting':
        return placement in view_based

    # plan view: everything except things that must be hosted or are adaptive
    blocked = [p for p in (fpt('OneLevelBasedHosted'), fpt('Adaptive')) if p]
    return placement not in blocked


def harvest(doc, kind):
    """-> ordered list of CatNode."""
    excluded = _excluded_bics()
    buckets = {}
    for fam in DB.FilteredElementCollector(doc).OfClass(DB.Family):
        try:
            if not family_allowed(fam, kind, excluded):
                continue
            sym_ids = list(fam.GetFamilySymbolIds())
            if not sym_ids:
                continue
            cat_name = fam.FamilyCategory.Name
            types = []
            for sid in sym_ids:
                sym = doc.GetElement(sid)
                if sym is None:
                    continue
                types.append(TypeNode(type_name(sym), sid))
            if not types:
                continue
            types.sort(key=lambda t: t.name.lower())
            buckets.setdefault(cat_name, []).append(
                FamilyNode(elem_name(fam), fam.Id, types))
        except Exception:
            continue

    cats = []
    for cat_name in sorted(buckets.keys(), key=lambda s: s.lower()):
        fams = buckets[cat_name]
        fams.sort(key=lambda f: f.name.lower())
        cats.append(CatNode(cat_name, fams))
    return cats


def multicat_tag_types(doc):
    out = []
    bic = getattr(DB.BuiltInCategory, 'OST_MultiCategoryTags', None)
    if bic is None:
        return out
    col = DB.FilteredElementCollector(doc).OfCategory(bic) \
            .WhereElementIsElementType().ToElements()
    for sym in col:
        try:
            out.append((u'{0} : {1}'.format(elem_name(sym.Family),
                                            type_name(sym)), sym.Id))
        except Exception:
            continue
    out.sort(key=lambda p: p[0].lower())
    return out


# ---------------------------------------------------------------------------
#  Tree model
# ---------------------------------------------------------------------------
class TypeNode(object):
    def __init__(self, name, symbol_id):
        self.name = name or u'<unnamed>'
        self.symbol_id = symbol_id
        self.checked = False
        self.row = None
        self.cb = None


class FamilyNode(object):
    def __init__(self, name, family_id, types):
        self.name = name
        self.family_id = family_id
        self.types = types
        self.expanded = False
        self.row = None
        self.cb = None
        self.glyph = None

    def state(self):
        on = sum(1 for t in self.types if t.checked)
        if on == 0:
            return False
        if on == len(self.types):
            return True
        return None

    def set_all(self, value):
        for t in self.types:
            t.checked = value


class CatNode(object):
    def __init__(self, name, families):
        self.name = name
        self.families = families
        self.expanded = False
        self.row = None
        self.cb = None
        self.glyph = None

    def all_types(self):
        for f in self.families:
            for t in f.types:
                yield t

    def state(self):
        total = 0
        on = 0
        for t in self.all_types():
            total += 1
            if t.checked:
                on += 1
        if on == 0:
            return False
        if on == total:
            return True
        return None

    def set_all(self, value):
        for f in self.families:
            f.set_all(value)


# ---------------------------------------------------------------------------
#  Placement engine
# ---------------------------------------------------------------------------
class Rec(object):
    def __init__(self, elem_id, point, first_of_family):
        self.elem_id = elem_id
        self.point = point
        self.first_of_family = first_of_family


def activate(doc, symbol):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()


def place_one(doc, symbol, point, view, level, is_drafting):
    """Place a single family instance, returning it or None."""
    activate(doc, symbol)
    placement = None
    try:
        placement = symbol.Family.FamilyPlacementType
    except Exception:
        pass

    seg = 1000.0 * MM
    line = DB.Line.CreateBound(point, DB.XYZ(point.X + seg, point.Y, point.Z))
    ns = DB.Structure.StructuralType.NonStructural

    if is_drafting or placement == fpt('ViewBased'):
        return doc.Create.NewFamilyInstance(point, symbol, view)

    if placement == fpt('CurveBasedDetail'):
        return doc.Create.NewFamilyInstance(line, symbol, view)

    if placement in (fpt('CurveBased'), fpt('CurveDrivenStructural')):
        if level is None:
            return doc.Create.NewFamilyInstance(line, symbol, view)
        return doc.Create.NewFamilyInstance(line, symbol, level, ns)

    if level is not None:
        return doc.Create.NewFamilyInstance(point, symbol, level, ns)
    return doc.Create.NewFamilyInstance(point, symbol, view)


def anchor_point(elem, fallback):
    """Where the instance actually ended up, which is what a tag offset has
    to be measured from. A detail item can land a little off the point it was
    asked for, and a curve-based one has no location point at all."""
    try:
        loc = elem.Location
        if isinstance(loc, DB.LocationPoint):
            return loc.Point
        if isinstance(loc, DB.LocationCurve):
            return loc.Curve.Evaluate(0.5, True)
    except Exception:
        pass
    try:
        box = elem.get_BoundingBox(None)
        if box is not None:
            return DB.XYZ((box.Min.X + box.Max.X) / 2.0,
                          (box.Min.Y + box.Max.Y) / 2.0,
                          fallback.Z)
    except Exception:
        pass
    return fallback


def make_tag(doc, view, elem, tag_type_id, point):
    """Create a tag. Revit ignores the creation point for some categories -
    detail items in a drafting view among them - and parks the head on the
    element, so the position is set explicitly afterwards instead."""
    try:
        sym = doc.GetElement(tag_type_id)
        if sym is not None and not sym.IsActive:
            sym.Activate()
            doc.Regenerate()
        ref = DB.Reference(elem)
        tag = DB.IndependentTag.Create(
            doc, tag_type_id, view.Id, ref, False,
            DB.TagOrientation.Horizontal, point)
        if tag is None:
            return None
        try:
            tag.HasLeader = False
        except Exception:
            pass
        return tag
    except Exception:
        return None


def set_tag_head(tag, point):
    """-> True if the head is within a millimetre of where it was asked for.
    Called after a regenerate, which is when the position will actually take."""
    try:
        tag.TagHeadPosition = point
    except Exception:
        return False
    try:
        return tag.TagHeadPosition.DistanceTo(point) < MM
    except Exception:
        return True


def text_note_types(doc):
    """-> [(name, TextNoteType)] alphabetical."""
    out = []
    try:
        for tnt in DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType):
            out.append((elem_name(tnt), tnt))
    except Exception:
        pass
    out.sort(key=lambda pair: pair[0].lower())
    return out


def find_text_type(doc, wanted):
    """-> (TextNoteType or None, matched_exactly)."""
    types = text_note_types(doc)
    if not types:
        return None, False
    wanted_l = (wanted or u'').strip().lower()
    for name, tnt in types:
        if name.strip().lower() == wanted_l:
            return tnt, True
    return types[0][1], False


def make_heading(doc, view, text, point, tnt):
    if tnt is None:
        return None
    try:
        return DB.TextNote.Create(doc, view.Id, point, text, tnt.Id)
    except Exception:
        return None


def user_worksets(doc):
    """-> [(name, Workset)] of every user workset, alphabetical."""
    out = []
    if not doc.IsWorkshared:
        return out
    try:
        for ws in DB.FilteredWorksetCollector(doc).OfKind(
                DB.WorksetKind.UserWorkset):
            out.append((ws.Name, ws))
    except Exception:
        pass
    out.sort(key=lambda pair: pair[0].lower())
    return out


def resolve_workset(doc, wanted):
    """-> (previous WorksetId or None, name actually used)."""
    if not doc.IsWorkshared:
        return None, u'Not workshared'
    table = doc.GetWorksetTable()
    previous = table.GetActiveWorksetId()
    wanted_l = (wanted or u'').strip().lower()
    if not wanted_l:
        try:
            return previous, table.GetWorkset(previous).Name + u' (active)'
        except Exception:
            return previous, u'Active workset'
    target = None
    try:
        for ws in DB.FilteredWorksetCollector(doc).OfKind(DB.WorksetKind.UserWorkset):
            if ws.Name.strip().lower() == wanted_l:
                target = ws
                break
    except Exception:
        target = None
    if target is not None:
        table.SetActiveWorksetId(target.Id)
        return previous, target.Name
    try:
        return previous, table.GetWorkset(previous).Name + u' (active - fallback)'
    except Exception:
        return previous, u'Active workset (fallback)'


def execute_placement(uiapp, req):
    uidoc = uiapp.ActiveUIDocument
    doc = uidoc.Document
    view = uidoc.ActiveView

    kind = view_kind(view)
    if kind is None:
        themed_dialog(u'Family Management Placer',
                      [(u'Unsupported view', 'head'),
                       (u'Switch to a floor plan or a drafting view and run '
                        u'the tool again.', 'body')],
                      footer=u'v' + TOOL_VERSION)
        return None
    if kind != req.kind:
        themed_dialog(u'Family Management Placer',
                      [(u'Active view changed', 'head'),
                       (u'The family list was built for a {0} view but the '
                        u'active view is now a {1} view. Press Reload in the '
                        u'tool window, then run again.'.format(req.kind, kind),
                        'warn')],
                      footer=u'v' + TOOL_VERSION)
        return None

    is_drafting = (kind == 'drafting')
    level = None if is_drafting else view.GenLevel

    try:
        start = uidoc.Selection.PickPoint(
            u'Click the start point - top-left of the family review layout')
    except OperationCanceledException:
        return None
    except Exception:
        return None

    base_z = level.Elevation if level is not None else start.Z

    def opt(name, key):
        return float(getattr(req, name, DEFAULTS[key]))

    fam_off_ft = opt('family_tag_offset', 'family_tag_offset') * MM
    type_off_ft = opt('type_tag_offset', 'type_tag_offset') * MM
    vert_ft = opt('family_spacing', 'family_spacing') * MM
    col_ft = opt('column_spacing', 'column_spacing') * MM
    gap_ft = vert_ft * (opt('group_gap', 'group_gap') / 100.0)
    head_ft = opt('heading_offset', 'heading_offset') * MM

    tnt, style_exact = find_text_type(
        doc, getattr(req, 'heading_style', DEFAULTS['heading_style']))
    if tnt is None:
        style_note = u'no text style in project'
    elif style_exact:
        style_note = elem_name(tnt)
    else:
        style_note = u'"{0}" not found - used {1}'.format(
            getattr(req, 'heading_style', u''), elem_name(tnt))

    prev_ws, ws_used = resolve_workset(
        doc, getattr(req, 'workset_name', u''))

    placed = {}
    skipped = {}
    tags_moved = 0
    records = []
    columns = []
    tags_made = 0
    heads_made = 0

    tgroup = DB.TransactionGroup(doc, u'RevoBIM PY | Family Management Placer')
    tgroup.Start()
    try:
        # ---- 1. instances -------------------------------------------------
        t = DB.Transaction(doc, u'RevoBIM PY | Place families')
        t.Start()
        col_index = 0
        for cat_name, fams in req.groups:
            x = start.X + col_index * col_ft
            columns.append((cat_name, x))
            placed[cat_name] = 0
            skipped[cat_name] = 0
            row_index = 0
            group_drop = 0.0
            fam_index = 0
            for fam_name, sym_ids in fams:
                if fam_index > 0:
                    group_drop += gap_ft
                fam_index += 1
                first = True
                for sid in sym_ids:
                    symbol = doc.GetElement(sid)
                    if symbol is None:
                        skipped[cat_name] += 1
                        continue
                    point = DB.XYZ(x, start.Y - row_index * vert_ft - group_drop,
                                   base_z)
                    inst = None
                    sub = DB.SubTransaction(doc)
                    sub.Start()
                    try:
                        inst = place_one(doc, symbol, point, view, level, is_drafting)
                        if inst is None:
                            sub.RollBack()
                        else:
                            sub.Commit()
                    except Exception:
                        try:
                            sub.RollBack()
                        except Exception:
                            pass
                        inst = None
                    if inst is None:
                        skipped[cat_name] += 1
                    else:
                        records.append(Rec(inst.Id, point, first))
                        placed[cat_name] += 1
                        row_index += 1
                        first = False
            col_index += 1
        t.Commit()

        # ---- 2. tags ------------------------------------------------------
        if getattr(req, 'do_tagging', True) and \
                (req.family_tag_id or req.type_tag_id):
            t2 = DB.Transaction(doc, u'RevoBIM PY | Tag families')
            t2.Start()
            doc.Regenerate()
            wanted = []
            for rec in records:
                elem = doc.GetElement(rec.elem_id)
                if elem is None:
                    continue
                p = anchor_point(elem, rec.point)
                if req.type_tag_id is not None:
                    target = DB.XYZ(p.X + type_off_ft, p.Y, p.Z)
                    tag = make_tag(doc, view, elem, req.type_tag_id, target)
                    if tag is not None:
                        tags_made += 1
                        wanted.append((tag, target))
                if rec.first_of_family and req.family_tag_id is not None:
                    target = DB.XYZ(p.X, p.Y + fam_off_ft, p.Z)
                    tag = make_tag(doc, view, elem, req.family_tag_id, target)
                    if tag is not None:
                        tags_made += 1
                        wanted.append((tag, target))

            # Revit parks the head on the element for some categories, so the
            # offsets are applied again after a regenerate, when they stick.
            doc.Regenerate()
            for tag, target in wanted:
                if set_tag_head(tag, target):
                    tags_moved += 1
            t2.Commit()

        # ---- 3. headings --------------------------------------------------
        t3 = DB.Transaction(doc, u'RevoBIM PY | Category headings')
        t3.Start()
        if getattr(req, 'show_headings', True):
            for cat_name, x in columns:
                hp = DB.XYZ(x, start.Y + head_ft, base_z)
                if make_heading(doc, view, cat_name, hp, tnt) is not None:
                    heads_made += 1
        t3.Commit()

        tgroup.Assimilate()
    except Exception:
        try:
            tgroup.RollBack()
        except Exception:
            pass
        raise
    finally:
        if prev_ws is not None:
            try:
                doc.GetWorksetTable().SetActiveWorksetId(prev_ws)
            except Exception:
                pass

    try:
        uidoc.RefreshActiveView()
    except Exception:
        pass

    return {
        'columns': columns,
        'placed': placed,
        'skipped': skipped,
        'tags': tags_made,
        'headings': heads_made,
        'workset': ws_used,
        'view': view.Name,
        'kind': kind,

        'heading_style': style_note,
        'headings_wanted': len(columns) if getattr(req, 'show_headings', True) else 0,
        'tags_moved': tags_moved,
        'scale': getattr(req, 'scale', 100.0),
    }


def report(result):
    if result is None:
        return
    rows = []
    total_p = 0
    total_s = 0
    for cat_name, _x in result['columns']:
        p = result['placed'].get(cat_name, 0)
        s = result['skipped'].get(cat_name, 0)
        total_p += p
        total_s += s
        rows.append((cat_name, p, s))
    rows.append((u'TOTAL', total_p, total_s))

    lines = [
        (u'Placement complete', 'head'),
        (u'{0} instances across {1} categories in "{2}".'.format(
            total_p, len(result['columns']), result['view']), 'body'),
    ]
    if total_s:
        lines.append((u'{0} types could not be placed in this view type and '
                      u'were skipped.'.format(total_s), 'warn'))
    lines.append((u'Tags: {0} placed, {1} positioned    Headings: {2}    '
                  u'Workset: {3}'.format(result['tags'], result['tags_moved'],
                                         result['headings'],
                                         result['workset']), 'muted'))

    if result['tags'] and result['tags_moved'] < result['tags']:
        lines.append((u'{0} tags would not move to their offset and are '
                      u'sitting on their element.'.format(
                          result['tags'] - result['tags_moved']), 'warn'))

    if result['headings_wanted']:
        lines.append((u'Heading text style: {0}'.format(
            result['heading_style']), 'muted'))
        missing = result['headings_wanted'] - result['headings']
        if missing > 0:
            lines.append((u'{0} headings could not be placed.'.format(missing),
                          'warn'))

    themed_dialog(u'Family Management Placer', lines,
                  footer=u'RevoBIM PY  v{0}   |   spacing 1:{1}'.format(
                      TOOL_VERSION, fmt_num(result['scale'])),
                  rows=rows)


# ---------------------------------------------------------------------------
#  External event handler
# ---------------------------------------------------------------------------
class PlacerHandler(IExternalEventHandler):
    def __init__(self):
        self.request = None
        self.owner = None
        self.stamp = TOOL_VERSION

    def Execute(self, uiapp):
        req = self.request
        self.request = None
        try:
            if req is None:
                return
            asked = getattr(req, 'tool_version', None)
            if asked != TOOL_VERSION:
                themed_dialog(
                    u'Family Management Placer',
                    [(u'Restart Revit to finish the upgrade', 'head'),
                     (u'This request came from version {0} but the running '
                      u'handler is version {1}. Revit keeps the handler for '
                      u'the whole session, so an upgraded script cannot take '
                      u'over until Revit is restarted.'.format(
                          asked or u'unknown', TOOL_VERSION), 'warn'),
                     (u'Nothing has been placed. Close Revit, reopen it, and '
                      u'run the tool again.', 'body')],
                    footer=u'RevoBIM PY  v' + TOOL_VERSION)
                return
            result = execute_placement(uiapp, req)

            # Nothing placed - a refusal or an escaped pick has already had
            # its say, so the window always comes back for another go.
            if result is None:
                self._finish(False, True)
                return

            if getattr(req, 'show_results', False):
                report(result)
            self._finish(True, getattr(req, 'keep_open', False))
        except Exception:
            # A failure is always reported, whatever the results setting says,
            # and always leaves the window open.
            themed_dialog(u'Family Management Placer',
                          [(u'Something went wrong', 'head'),
                           (traceback.format_exc()[-1400:], 'muted')],
                          footer=u'v' + TOOL_VERSION)
            self._finish(False, True)

    def _finish(self, placed, keep_open):
        if self.owner is None:
            return
        try:
            if keep_open:
                self.owner.restore()
            else:
                self.owner.shutdown()
        except Exception:
            pass

    def GetName(self):
        return u'RevoBIM PY Family Management Placer'


# ---------------------------------------------------------------------------
#  Settings window
# ---------------------------------------------------------------------------
class SettingsWindow(object):
    """Modal. Edits a working copy of the owner's settings and only writes
    them back on Save, so Cancel really does discard."""

    def __init__(self, owner):
        self.owner = owner
        self.doc = owner.doc
        self.cfg = dict(owner.cfg)
        self.scale = float(owner.scale)
        self.saved = False
        self._scale_ready = False

        self.win = load_xaml(SETTINGS_XAML)
        self.win.FindName('verLabel').Text = u'v' + TOOL_VERSION
        try:
            self.win.Owner = owner.win
        except Exception:
            pass

        f = self.win.FindName
        self.cbo_scale = f('cboScale')
        self.txt_vert = f('txtVert')
        self.txt_col = f('txtCol')
        self.txt_gap = f('txtGap')
        self.chk_tag = f('chkTag')
        self.cbo_fam = f('cboFamTag')
        self.cbo_type = f('cboTypeTag')
        self.txt_fam_off = f('txtFamOff')
        self.txt_type_off = f('txtTypeOff')
        self.chk_head = f('chkHead')
        self.cbo_head_style = f('cboHeadStyle')
        self.txt_head_off = f('txtHeadOff')
        self.chk_results = f('chkResults')
        self.chk_keep = f('chkKeepOpen')
        self.cbo_ws = f('cboWorkset')

        self._fill_scale()
        self._fill_tags()
        self._fill_heading_styles()
        self._fill_worksets()
        self.to_fields()

        f('titleBar').MouseLeftButtonDown += self.on_drag
        f('btnClose').Click += lambda s, e: self.win.Close()
        f('btnCancel').Click += lambda s, e: self.win.Close()
        f('btnSave').Click += self.on_save
        f('btnReset').Click += self.on_reset

    def on_drag(self, sender, args):
        try:
            self.win.DragMove()
        except Exception:
            pass

    # -- population -------------------------------------------------------
    def _fill_scale(self):
        self._scale_ready = False
        self.cbo_scale.Items.Clear()
        values = [v for _lbl, v in SCALE_STEPS]
        if not any(abs(self.scale - v) < 1e-6 for v in values):
            values.append(self.scale)
        values.sort(reverse=True)
        chosen = None
        for value in values:
            item = ComboBoxItem()
            item.Content = u'1:' + fmt_num(value)
            item.Tag = float(value)
            self.cbo_scale.Items.Add(item)
            if abs(float(value) - self.scale) < 1e-6:
                chosen = item
        self.cbo_scale.SelectedItem = chosen or self.cbo_scale.Items[0]
        self.cbo_scale.SelectionChanged += self.on_scale
        self._scale_ready = True

        found = self.owner.view_scale()
        self.win.FindName('scaleLabel').Text = (
            u'Active view is 1:{0}.'.format(fmt_num(found)) if found
            else u'Active view reports no scale.')

    def _fill_tags(self):
        for combo, key in ((self.cbo_fam, 'family_tag'),
                           (self.cbo_type, 'type_tag')):
            combo.Items.Clear()
            none_item = ComboBoxItem()
            none_item.Content = u'< none >'
            none_item.Tag = None
            combo.Items.Add(none_item)
            wanted = (self.cfg.get(key) or u'').strip().lower()
            chosen = none_item
            for name, sid in self.owner.tag_types:
                item = ComboBoxItem()
                item.Content = name
                item.Tag = sid
                combo.Items.Add(item)
                if name.strip().lower() == wanted:
                    chosen = item
            combo.SelectedItem = chosen

        if not self.owner.tag_types:
            self.chk_tag.IsChecked = False
            self.chk_tag.IsEnabled = False
            self.chk_tag.Content = u'No Multi-Category tags loaded'

    def _fill_heading_styles(self):
        types = text_note_types(self.doc)
        self.cbo_head_style.Items.Clear()
        wanted = (self.cfg.get('heading_style') or u'').strip().lower()
        chosen = None
        for name, tnt in types:
            item = ComboBoxItem()
            item.Content = name
            item.Tag = tnt.Id
            self.cbo_head_style.Items.Add(item)
            if name.strip().lower() == wanted:
                chosen = item

        label = self.win.FindName('headStyleLabel')
        if not types:
            self.cbo_head_style.IsEnabled = False
            label.Text = u'No text styles in this project.'
            return
        self.cbo_head_style.IsEnabled = True
        if chosen is None:
            chosen = self.cbo_head_style.Items[0]
            label.Text = (
                u'Remembered style "{0}" is not in this model - using "{1}".'
                .format(self.cfg.get('heading_style'), chosen.Content)
                if wanted else u'{0} styles available.'.format(len(types)))
        else:
            label.Text = u'{0} styles available.'.format(len(types))
        self.cbo_head_style.SelectedItem = chosen

    def _fill_worksets(self):
        self.cbo_ws.Items.Clear()
        active = ComboBoxItem()
        active.Content = u'< active workset >'
        active.Tag = u''
        self.cbo_ws.Items.Add(active)
        label = self.win.FindName('wsLabel')

        if not self.doc.IsWorkshared:
            self.cbo_ws.SelectedItem = active
            self.cbo_ws.IsEnabled = False
            label.Text = u'Model is not workshared - worksets do not apply.'
            return

        self.cbo_ws.IsEnabled = True
        wanted = (self.cfg.get('workset_name') or u'').strip().lower()
        chosen = None
        for name, _ws in user_worksets(self.doc):
            item = ComboBoxItem()
            item.Content = name
            item.Tag = name
            self.cbo_ws.Items.Add(item)
            if name.strip().lower() == wanted:
                chosen = item

        if chosen is not None:
            label.Text = u'Elements will be created on "{0}".'.format(chosen.Tag)
        elif wanted:
            label.Text = (u'Remembered workset "{0}" is not in this model - '
                          u'using the active workset.'
                          .format(self.cfg.get('workset_name')))
        else:
            label.Text = u'Elements will be created on the active workset.'
        self.cbo_ws.SelectedItem = chosen or active

    # -- fields <-> working copy ------------------------------------------
    def scale_fields(self):
        return ((self.txt_fam_off, 'family_tag_offset'),
                (self.txt_type_off, 'type_tag_offset'),
                (self.txt_vert, 'family_spacing'),
                (self.txt_col, 'column_spacing'),
                (self.txt_head_off, 'heading_offset'))

    def to_fields(self):
        f = self.scale / 100.0
        for box, key in self.scale_fields():
            box.Text = fmt_num(self.cfg.get(key, DEFAULTS[key] * f))
        self.txt_gap.Text = fmt_num(self.cfg.get('group_gap',
                                                 DEFAULTS['group_gap']))
        self.chk_tag.IsChecked = bool(self.cfg.get('do_tagging'))
        self.chk_head.IsChecked = bool(self.cfg.get('show_headings'))
        self.chk_results.IsChecked = bool(self.cfg.get('show_results'))
        self.chk_keep.IsChecked = bool(self.cfg.get('keep_open'))
        self.refresh_notes()

    def from_fields(self):
        f = self.scale / 100.0
        for box, key in self.scale_fields():
            minimum = 0.001 if key in ('family_spacing', 'column_spacing') else 0.0
            self.cfg[key] = to_float(box.Text, DEFAULTS[key] * f,
                                     minimum=minimum)
        self.cfg['group_gap'] = to_float(self.txt_gap.Text,
                                         DEFAULTS['group_gap'], minimum=0.0)
        self.cfg['do_tagging'] = bool(self.chk_tag.IsChecked)
        self.cfg['show_headings'] = bool(self.chk_head.IsChecked)
        self.cfg['show_results'] = bool(self.chk_results.IsChecked)
        self.cfg['keep_open'] = bool(self.chk_keep.IsChecked)
        self.cfg['family_tag'] = self._combo_text(self.cbo_fam)
        self.cfg['type_tag'] = self._combo_text(self.cbo_type)
        self.cfg['heading_style'] = self._combo_text(self.cbo_head_style)
        self.cfg['workset_name'] = u''
        if self.cbo_ws.SelectedItem is not None:
            self.cfg['workset_name'] = u'{0}'.format(
                self.cbo_ws.SelectedItem.Tag or u'')

    def _combo_text(self, combo):
        item = combo.SelectedItem
        if item is None or item.Tag is None:
            return u''
        return u'{0}'.format(item.Content)

    def refresh_notes(self):
        f = self.scale / 100.0
        for box, key, label, quoted, divisor in (
                (self.txt_fam_off, 'family_tag_offset', 'famOffLabel', 1.0, 1.0),
                (self.txt_type_off, 'type_tag_offset', 'typeOffLabel', 1.0, 1.0),
                (self.txt_head_off, 'heading_offset', 'headOffLabel', 50.0, 1.0)):
            shown = to_float(box.Text, DEFAULTS[key] * f, minimum=0.0)
            at = shown * (quoted / max(self.scale, 1e-9))
            self.win.FindName(label).Text = u'{0} mm at 1:{1}'.format(
                fmt_num(at), fmt_num(quoted))

    # -- actions -----------------------------------------------------------
    def on_scale(self, sender, args):
        if not self._scale_ready or self.cbo_scale.SelectedItem is None:
            return
        new_scale = float(self.cbo_scale.SelectedItem.Tag)
        if abs(new_scale - self.scale) < 1e-9:
            return
        self.from_fields()
        old_f = self.scale / 100.0
        new_f = new_scale / 100.0
        for _box, key in self.scale_fields():
            self.cfg[key] = (float(self.cfg[key]) / old_f) * new_f
        self.scale = new_scale
        self.to_fields()

    def on_reset(self, sender, args):
        self.cfg = dict(DEFAULTS)
        f = self.scale / 100.0
        for key in SCALED_KEYS:
            self.cfg[key] = DEFAULTS[key] * f
        self._fill_tags()
        self._fill_heading_styles()
        self._fill_worksets()
        self.to_fields()

    def on_save(self, sender, args):
        self.from_fields()
        self.owner.cfg.update(self.cfg)
        self.owner.scale = self.scale
        self.saved = True
        self.win.Close()

    def show(self):
        self.win.ShowDialog()
        return self.saved


# ---------------------------------------------------------------------------
#  Main window
# ---------------------------------------------------------------------------
class PlacerWindow(object):

    def __init__(self, doc, uidoc):
        self.doc = doc
        self.uidoc = uidoc
        self.cfg = load_settings()
        self.scale = float(DEFAULTS['scale'])
        self.cats = []
        self.kind = None
        self.tag_types = []

        self.win = load_xaml(MAIN_XAML)
        self.win.FindName('verLabel').Text = u'v' + TOOL_VERSION

        self.rows_panel = self.win.FindName('rowsPanel')
        self.status = self.win.FindName('statusLabel')
        self.scope = self.win.FindName('scopeLabel')
        self.cfg_label = self.win.FindName('cfgLabel')
        self.filter = self.win.FindName('txtFilter')

        self._wire()
        self.reload()

    # -- scale ------------------------------------------------------------
    def view_scale(self):
        """The active view's own scale, or None if it will not report one."""
        try:
            value = float(self.uidoc.ActiveView.Scale)
            if value > 0:
                return value
        except Exception:
            pass
        return None

    def rescale_to(self, new_scale):
        """Move every scaled distance in cfg from the current scale to a new
        one. Values are converted rather than reset, so a hand edit survives."""
        new_scale = float(new_scale)
        if abs(new_scale - self.scale) < 1e-9:
            return
        old_f = self.scale / 100.0
        new_f = new_scale / 100.0
        for key in SCALED_KEYS:
            value = float(self.cfg.get(key, DEFAULTS[key] * old_f))
            self.cfg[key] = (value / old_f) * new_f
        self.scale = new_scale

    def apply_view_scale(self):
        found = self.view_scale()
        if found is None:
            return u'Active view reports no scale - left at 1:{0}.'.format(
                fmt_num(self.scale))
        self.rescale_to(found)
        return u'Scale 1:{0}, from the active view.'.format(fmt_num(found))

    # -- summary line ------------------------------------------------------
    def refresh_cfg_label(self):
        tag_note = u'tags off'
        if self.cfg.get('do_tagging'):
            bits = []
            if self.cfg.get('family_tag'):
                bits.append(u'family')
            if self.cfg.get('type_tag'):
                bits.append(u'type')
            tag_note = (u'tagging ' + u' + '.join(bits)) if bits else \
                u'tagging on, no tag type picked'
        head_note = (u'headings on' if self.cfg.get('show_headings')
                     else u'headings off')
        ws = self.cfg.get('workset_name') or u'active workset'
        after = []
        if self.cfg.get('show_results'):
            after.append(u'results')
        if self.cfg.get('keep_open'):
            after.append(u'stay open')
        after_note = (u' + '.join(after)) if after else u'close silently'
        self.cfg_label.Text = (
            u'1:{0}   |   rows {1} mm, columns {2} mm, group gap {3}%   |   '
            u'{4}   |   {5}   |   workset: {6}   |   after: {7}'.format(
                fmt_num(self.scale),
                fmt_num(self.cfg.get('family_spacing', 0)),
                fmt_num(self.cfg.get('column_spacing', 0)),
                fmt_num(self.cfg.get('group_gap', 0)),
                tag_note, head_note, ws, after_note))

    def open_settings(self, sender, args):
        dlg = SettingsWindow(self)
        if dlg.show():
            save_settings(self.remembered())
            self.refresh_cfg_label()
            self.set_status(u'Settings saved.')

    def remembered(self):
        keep = dict(DEFAULTS)
        for key in REMEMBERED_KEYS:
            if key in self.cfg:
                keep[key] = self.cfg[key]
        return keep

    def _wire(self):
        w = self.win
        w.FindName('titleBar').MouseLeftButtonDown += self.on_drag
        w.FindName('btnClose').Click += self.on_close
        w.FindName('btnCancel').Click += self.on_close
        w.FindName('btnRun').Click += self.on_run
        w.FindName('btnSettings').Click += self.open_settings
        w.FindName('btnReload').Click += lambda s, e: self.reload()
        w.FindName('btnAll').Click += lambda s, e: self.set_all(True)
        w.FindName('btnNone').Click += lambda s, e: self.set_all(False)
        w.FindName('btnExpand').Click += lambda s, e: self.expand_all(True)
        w.FindName('btnCollapse').Click += lambda s, e: self.expand_all(False)
        self.filter.TextChanged += lambda s, e: self.build_tree()
        w.Closing += self.on_closing

    def on_drag(self, sender, args):
        try:
            self.win.DragMove()
        except Exception:
            pass

    # -- data -------------------------------------------------------------
    def reload(self):
        view = self.uidoc.ActiveView
        self.kind = view_kind(view)
        if self.kind is None:
            self.scope.Text = (u'Active view is not a floor plan or drafting '
                               u'view - switch view and press Reload.')
            self.cats = []
            self.build_tree()
            self.refresh_cfg_label()
            self.set_status(u'No compatible view active.')
            return

        self.cats = harvest(self.doc, self.kind)
        self.tag_types = multicat_tag_types(self.doc)

        scale_note = self.apply_view_scale()

        n_fam = sum(len(c.families) for c in self.cats)
        n_typ = sum(len(list(c.all_types())) for c in self.cats)
        label = u'Floor plan' if self.kind == 'plan' else u'Drafting view'
        note = u'' if self.kind == 'plan' else u' - view-based families only'
        self.scope.Text = (
            u'{0}: "{1}"{2}   |   {3} categories, {4} families, {5} types'
            .format(label, view.Name, note, len(self.cats), n_fam, n_typ))

        self.build_tree()
        self.refresh_cfg_label()
        self.refresh_status()
        if scale_note:
            self.set_status(self.status.Text + u'   ' + scale_note)

    def build_tree(self):
        self.rows_panel.Children.Clear()
        for cat in self.cats:
            cat.row = None
            cat.cb = None
            cat.glyph = None
            cat.expanded = False
            for fam in cat.families:
                fam.row = None
                fam.cb = None
                fam.glyph = None
                fam.expanded = False
                for typ in fam.types:
                    typ.row = None
                    typ.cb = None

        needle = self.filter.Text.strip().lower()
        for cat in self.cats:
            if needle:
                hits = [f for f in cat.families
                        if needle in f.name.lower()
                        or needle in cat.name.lower()
                        or any(needle in t.name.lower() for t in f.types)]
                if not hits:
                    continue
                cat.row = self._make_row(cat, 'cat', 0)
                self.rows_panel.Children.Add(cat.row)
                cat.expanded = True
                cat.glyph.Text = GLYPH_OPEN
                for fam in hits:
                    fam.row = self._make_row(fam, 'fam', 20)
                    self.rows_panel.Children.Add(fam.row)
            else:
                cat.row = self._make_row(cat, 'cat', 0)
                self.rows_panel.Children.Add(cat.row)
        self.sync_checks()

    def _make_row(self, node, kind, indent):
        border = Border()
        border.Padding = Thickness(indent + 4, 2, 4, 2)
        border.Background = Brushes.Transparent

        sp = StackPanel()
        sp.Orientation = Orientation.Horizontal

        glyph = TextBlock()
        glyph.Width = 16
        glyph.FontSize = 9
        glyph.Foreground = brush(CLR_MUTED)
        glyph.VerticalAlignment = VerticalAlignment.Center
        glyph.Background = Brushes.Transparent
        if kind in ('cat', 'fam'):
            glyph.Text = GLYPH_CLOSED
            glyph.Cursor = Cursors.Hand
            glyph.MouseLeftButtonUp += self._make_toggle(node, kind)
            node.glyph = glyph
        else:
            glyph.Text = u''
        sp.Children.Add(glyph)

        cb = CheckBox()
        cb.IsThreeState = False
        cb.VerticalAlignment = VerticalAlignment.Center
        cb.Margin = Thickness(0, 0, 6, 0)
        cb.Tag = (node, kind)
        cb.Click += self.on_check
        sp.Children.Add(cb)
        node.cb = cb

        label = TextBlock()
        label.Text = node.name
        label.MaxWidth = 430
        label.TextTrimming = TextTrimming.CharacterEllipsis
        label.VerticalAlignment = VerticalAlignment.Center
        if kind == 'cat':
            label.Foreground = brush(CLR_BLUE)
            label.FontWeight = FontWeights.SemiBold
        elif kind == 'fam':
            label.Foreground = brush(CLR_TEXT)
        else:
            label.Foreground = brush(CLR_MUTED)
        sp.Children.Add(label)

        meta = TextBlock()
        meta.Margin = Thickness(8, 0, 0, 0)
        meta.FontSize = 10
        meta.Foreground = brush(CLR_MUTED)
        meta.VerticalAlignment = VerticalAlignment.Center
        if kind == 'cat':
            meta.Text = u'{0} families / {1} types'.format(
                len(node.families), len(list(node.all_types())))
        elif kind == 'fam':
            meta.Text = u'{0} types'.format(len(node.types))
        else:
            meta.Text = u''
        sp.Children.Add(meta)

        border.Child = sp
        return border

    def _make_toggle(self, node, kind):
        def handler(sender, args):
            if node.expanded:
                self._collapse(node, kind)
            else:
                self._expand(node, kind)
        return handler

    def _expand(self, node, kind):
        node.expanded = True
        if node.glyph is not None:
            node.glyph.Text = GLYPH_OPEN
        index = self.rows_panel.Children.IndexOf(node.row) + 1
        children = node.families if kind == 'cat' else node.types
        child_kind = 'fam' if kind == 'cat' else 'typ'
        indent = 20 if kind == 'cat' else 40
        for child in children:
            child.row = self._make_row(child, child_kind, indent)
            self.rows_panel.Children.Insert(index, child.row)
            index += 1
        self.sync_checks()

    def _collapse(self, node, kind):
        node.expanded = False
        if node.glyph is not None:
            node.glyph.Text = GLYPH_CLOSED
        children = node.families if kind == 'cat' else node.types
        child_kind = 'fam' if kind == 'cat' else 'typ'
        for child in children:
            if child_kind == 'fam' and child.expanded:
                self._collapse(child, 'fam')
            if child.row is not None:
                self.rows_panel.Children.Remove(child.row)
                child.row = None
                child.cb = None
                child.glyph = None

    def expand_all(self, value):
        if not value:
            for cat in self.cats:
                if cat.expanded:
                    self._collapse(cat, 'cat')
            return
        for cat in self.cats:
            if cat.row is not None and not cat.expanded:
                self._expand(cat, 'cat')

    # -- selection --------------------------------------------------------
    def on_check(self, sender, args):
        node, kind = sender.Tag
        value = bool(sender.IsChecked)
        if kind == 'typ':
            node.checked = value
        else:
            node.set_all(value)
        self.sync_checks()
        self.refresh_status()

    def set_all(self, value):
        for cat in self.cats:
            cat.set_all(value)
        self.sync_checks()
        self.refresh_status()

    def sync_checks(self):
        for cat in self.cats:
            if cat.cb is not None:
                cat.cb.IsChecked = cat.state()
            for fam in cat.families:
                if fam.cb is not None:
                    fam.cb.IsChecked = fam.state()
                for typ in fam.types:
                    if typ.cb is not None:
                        typ.cb.IsChecked = typ.checked

    def selection(self):
        """-> ordered [(cat_name, [(fam_name, [symbol_id,...]), ...]), ...]"""
        groups = []
        for cat in self.cats:
            fams = []
            for fam in cat.families:
                ids = [t.symbol_id for t in fam.types if t.checked]
                if ids:
                    fams.append((fam.name, ids))
            if fams:
                groups.append((cat.name, fams))
        return groups

    def refresh_status(self):
        groups = self.selection()
        n_typ = sum(len(ids) for _c, fams in groups for _f, ids in fams)
        n_fam = sum(len(fams) for _c, fams in groups)
        self.set_status(u'{0} categories / {1} families / {2} types selected.'
                        .format(len(groups), n_fam, n_typ))

    def set_status(self, text):
        self.status.Text = text

    # -- run --------------------------------------------------------------
    def gather(self):
        c = self.cfg
        req = type('Req', (object,), {})()
        req.tool_version = TOOL_VERSION
        req.groups = self.selection()
        req.kind = self.kind
        req.scale = self.scale

        f = self.scale / 100.0
        for key in SCALED_KEYS:
            setattr(req, key, float(c.get(key, DEFAULTS[key] * f)))
        req.group_gap = float(c.get('group_gap', DEFAULTS['group_gap']))

        req.workset_name = c.get('workset_name') or u''
        req.do_tagging = bool(c.get('do_tagging'))
        req.show_headings = bool(c.get('show_headings'))
        req.show_results = bool(c.get('show_results'))
        req.keep_open = bool(c.get('keep_open'))
        req.heading_style = c.get('heading_style') or u''

        req.family_tag_id = None
        req.type_tag_id = None
        if req.do_tagging:
            wanted_fam = (c.get('family_tag') or u'').strip().lower()
            wanted_type = (c.get('type_tag') or u'').strip().lower()
            for name, sid in self.tag_types:
                low = name.strip().lower()
                if low == wanted_fam:
                    req.family_tag_id = sid
                if low == wanted_type:
                    req.type_tag_id = sid
        return req

    def on_run(self, sender, args):
        req = self.gather()
        if not req.groups:
            self.set_status(u'Nothing selected - tick at least one family or type.')
            return
        HANDLER.request = req
        HANDLER.owner = self
        self.set_status(u'Pick the start point in the active view...')
        self.win.Hide()
        EVENT.Raise()

    def shutdown(self):
        """Close the tool after a run. on_closing saves the settings."""
        try:
            self.win.Close()
        except Exception:
            pass

    def restore(self):
        try:
            self.win.Show()
            self.win.Activate()
            self.refresh_status()
        except Exception:
            pass

    # -- lifecycle --------------------------------------------------------
    def on_close(self, sender, args):
        self.win.Close()

    def on_closing(self, sender, args):
        # remembered choices are kept; every distance restarts from the
        # defaults, since the scale is taken from the view on the next open
        try:
            save_settings(self.remembered())
        except Exception:
            pass
        try:
            AppDomain.CurrentDomain.SetData(DOMAIN_KEY, None)
        except Exception:
            pass

    def show(self):
        own_to_revit(self.win)
        self.win.Show()


# ---------------------------------------------------------------------------
#  Entry point
# ---------------------------------------------------------------------------
# The keys carry the version. An ExternalEvent handler parked in the AppDomain
# outlives the script, and a cached handler from an older build still holds
# that build's globals - so it would keep running the previous version's
# placement code against a request built by the new window. Stamping the key
# means an upgraded script always gets a handler of its own.
EVENT_KEY = DOMAIN_KEY + '_event_' + TOOL_VERSION
HANDLER_KEY = DOMAIN_KEY + '_handler_' + TOOL_VERSION


def get_event():
    """Reuse one handler / ExternalEvent pair per version, per session."""
    domain = AppDomain.CurrentDomain
    handler = domain.GetData(HANDLER_KEY)
    event = domain.GetData(EVENT_KEY)
    if handler is None or event is None or \
            getattr(handler, 'stamp', None) != TOOL_VERSION:
        handler = PlacerHandler()
        event = ExternalEvent.Create(handler)
        domain.SetData(HANDLER_KEY, handler)
        domain.SetData(EVENT_KEY, event)
    # drop anything left by a build that did not stamp its keys
    try:
        domain.SetData(DOMAIN_KEY + '_event', None)
        domain.SetData(DOMAIN_KEY + '_handler', None)
    except Exception:
        pass
    return handler, event


HANDLER, EVENT = get_event()


def main():
    doc = revit.doc
    uidoc = revit.uidoc

    if doc is None or uidoc is None:
        return

    # close any window left over from a previous run
    try:
        old = AppDomain.CurrentDomain.GetData(DOMAIN_KEY)
        if old is not None:
            old.Close()
    except Exception:
        pass
    AppDomain.CurrentDomain.SetData(DOMAIN_KEY, None)

    if view_kind(uidoc.ActiveView) is None:
        themed_dialog(
            u'Family Management Placer',
            [(u'Open a floor plan or drafting view', 'head'),
             (u'This tool lays families out on the active view, so it needs a '
              u'floor plan (or ceiling / engineering plan) or a drafting view '
              u'to be active.', 'body'),
             (u'Active view: "{0}"  ({1})'.format(uidoc.ActiveView.Name,
                                                  uidoc.ActiveView.ViewType),
              'muted')],
            footer=u'RevoBIM PY  v' + TOOL_VERSION)
        return

    ui = PlacerWindow(doc, uidoc)
    AppDomain.CurrentDomain.SetData(DOMAIN_KEY, ui.win)
    ui.show()


main()
