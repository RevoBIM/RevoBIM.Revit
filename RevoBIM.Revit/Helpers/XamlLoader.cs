using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Text;
using System.Windows;
using System.Windows.Markup;
using System.Xml;
using System.Xml.Linq;

using Expression = System.Linq.Expressions.Expression;

namespace RevoBIM.Helpers
{
    /// <summary>
    /// Loads pyRevit XAML layouts verbatim. pyRevit wires handlers named in the XAML (Click="apply_click");
    /// XamlReader cannot, so those attributes are lifted out before loading and wired afterwards, by name, to the
    /// handlers the window passes in. An element without an x:Name is given one so it can be found again.
    /// Any CLR event is handled: the handler is adapted to the event's own delegate type.
    /// </summary>
    public static class XamlLoader
    {
        private static readonly XNamespace X = "http://schemas.microsoft.com/winfx/2006/xaml";

        /// <summary>The event attributes pyRevit layouts use to name a handler.</summary>
        private static readonly HashSet<string> Events = new HashSet<string>
        {
            "Click", "TextChanged", "MouseLeftButtonDown", "MouseLeftButtonUp", "PreviewMouseLeftButtonDown", "MouseDoubleClick",
            "SelectionChanged", "SelectedItemChanged", "Checked", "Unchecked", "Loaded", "GotFocus", "LostFocus", "KeyDown",
            "PreviewKeyDown", "KeyUp", "MouseEnter", "MouseLeave", "SizeChanged", "Closing", "Closed", "ValueChanged",
            "DropDownOpened", "DropDownClosed", "MouseDown", "PreviewMouseDown", "PreviewTextInput", "TextInput",
            "ScrollChanged", "Drop", "DragOver", "DragDelta", "ContextMenuOpening", "Activated", "Deactivated",
            "SourceUpdated", "TargetUpdated", "LayoutUpdated", "MouseWheel", "PreviewMouseWheel", "MouseMove",
        };

        private sealed class Hook
        {
            public string Element, Event, Handler;
        }

        public static string ReadResource(string name)
        {
            using (Stream stream = typeof(XamlLoader).Assembly.GetManifestResourceStream(name))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + name + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>
        /// Loads the layout (an embedded resource name). `edit` may rewrite the XAML text first (a tool that has to adjust
        /// a verbatim layout does it there, in one place). Every handler named in the XAML must be in `handlers`.
        /// </summary>
        public static T Load<T>(string resource, IDictionary<string, Action<object, EventArgs>> handlers, Func<string, string> edit = null)
            where T : DependencyObject
        {
            string text = ReadResource(resource);
            if (edit != null) text = edit(text);
            XDocument doc = XDocument.Parse(text, LoadOptions.PreserveWhitespace);
            var hooks = new List<Hook>();
            int counter = 0;
            foreach (XElement element in doc.Descendants().ToList())
            {
                foreach (XAttribute attr in element.Attributes().ToList())
                {
                    if (attr.IsNamespaceDeclaration || attr.Name.Namespace != XNamespace.None) continue;
                    string ev = attr.Name.LocalName;
                    if (!Events.Contains(ev)) continue;
                    string value = attr.Value;
                    if (value.Length == 0 || value.StartsWith("{", StringComparison.Ordinal)) continue;
                    // a handler is a plain identifier; "True" on a Checked attribute etc. is never one the window defines
                    if (handlers == null || !handlers.ContainsKey(value))
                    {
                        if (ev == "Checked" || ev == "Unchecked") continue;
                        throw new InvalidOperationException("no handler " + value + " (" + ev + ") given for " + resource);
                    }
                    string name = (string)element.Attribute(X + "Name");
                    if (string.IsNullOrEmpty(name))
                    {
                        name = "xlHook" + counter++;
                        element.SetAttributeValue(X + "Name", name);
                    }
                    hooks.Add(new Hook { Element = name, Event = ev, Handler = value });
                    attr.Remove();
                }
            }
            object loaded;
            using (XmlReader reader = XmlReader.Create(new StringReader(doc.ToString(SaveOptions.DisableFormatting))))
                loaded = XamlReader.Load(reader);
            var root = loaded as T;
            if (root == null) throw new InvalidCastException(resource + " is not a " + typeof(T).Name);

            foreach (Hook hook in hooks)
            {
                object target = FindName(root, hook.Element);
                if (target == null) throw new InvalidOperationException("could not find " + hook.Element + " to wire " + hook.Handler + " in " + resource);
                EventInfo ei = target.GetType().GetEvent(hook.Event);
                if (ei == null) throw new InvalidOperationException(target.GetType().Name + " has no event " + hook.Event + " (" + resource + ")");
                ei.AddEventHandler(target, Adapt(ei.EventHandlerType, handlers[hook.Handler]));
            }
            return root;
        }

        private static object FindName(DependencyObject root, string name)
        {
            var fe = root as FrameworkElement;
            if (fe != null)
            {
                object found = fe.FindName(name);
                if (found != null) return found;
            }
            var fce = root as FrameworkContentElement;
            return fce == null ? null : fce.FindName(name);
        }

        /// <summary>Adapts Action(sender, args) to the event's own delegate type (any two-argument handler whose args derive from EventArgs).</summary>
        private static Delegate Adapt(Type handlerType, Action<object, EventArgs> handler)
        {
            MethodInfo invoke = handlerType.GetMethod("Invoke");
            ParameterExpression[] ps = invoke.GetParameters().Select(p => Expression.Parameter(p.ParameterType)).ToArray();
            Expression call = Expression.Call(Expression.Constant(handler), typeof(Action<object, EventArgs>).GetMethod("Invoke"),
                                              Expression.Convert(ps[0], typeof(object)), Expression.Convert(ps[1], typeof(EventArgs)));
            return Expression.Lambda(handlerType, call, ps).Compile();
        }
    }
}
