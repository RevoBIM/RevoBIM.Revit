# Family Param Push changelog

## 1.2.0
- New tab, Family Param - Replace. Pick loadable families, map family parameters
  to shared parameters, press Replace. Each family is opened, its parameters are
  replaced, it is loaded back, and every instance and type value in the project
  is written to the new parameter and read back. Originals are saved to a backup
  file first. The first tab is now Family Param - Push.

## 1.1.0
- Save Mappings: name and save everything mapped on the right. Pick a saved set
  and press Load to bring it back, in this project or another using the same
  families. Delete removes one. A load adds to what is on screen and reports
  anything this model does not have.

## 1.0.2
- Fixed "Object reference not set to an instance of an object" on Run when a
  target number parameter had no value yet. Nothing was written by the failure.

## 1.0.1
- Fixed the load failure "Cannot import name PresentationSource": it lives in
  System.Windows, not System.Windows.Media. The bench stub had the same mistake,
  so a new rule checks every imported .NET name against a separate table.

## 1.0.0
- First version. Family list with category dropdown and search, push families
  and types to the right, per-family parameter mappings, Run bottom right.
