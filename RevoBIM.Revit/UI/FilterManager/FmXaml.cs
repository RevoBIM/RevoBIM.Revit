using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Markup;
using System.Xml;
using System.Xml.Linq;
using Expression = System.Linq.Expressions.Expression;

namespace RevoBIM.UI.FilterManager
{
    /// <summary>
    /// Loads the pyRevit XAML layouts verbatim. The pyRevit windows name their handlers in the XAML
    /// (Click="on_shrink"); XamlReader cannot wire those without code-behind, so the attributes are lifted out
    /// before loading and wired afterwards by name: on_shrink finds a method called OnShrink (case-insensitive,
    /// underscores ignored) on the owner. Every wired handler is guarded, so an error is reported, not swallowed.
    /// </summary>
    public static class FmXaml
    {
        private const string LayoutPrefix = "RevoBIM.UI.FilterManager.Layouts.";
        private static readonly XNamespace X = "http://schemas.microsoft.com/winfx/2006/xaml";

        private class Hook
        {
            public string ElementName, Event, Handler;
        }

        public static string ReadLayout(string fileName)
        {
            using (Stream stream = typeof(FmXaml).Assembly.GetManifestResourceStream(LayoutPrefix + fileName))
            {
                if (stream == null) throw new FileNotFoundException("embedded layout " + LayoutPrefix + fileName + " was not found");
                using (var reader = new StreamReader(stream, Encoding.UTF8)) return reader.ReadToEnd();
            }
        }

        /// <summary>Load a layout as a Window and wire its on_* handlers to methods of owner.</summary>
        public static T Load<T>(string fileName, object owner) where T : FrameworkElement
        {
            XDocument doc = XDocument.Parse(ReadLayout(fileName), LoadOptions.PreserveWhitespace);
            var hooks = new List<Hook>();
            int counter = 0;
            foreach (XElement element in doc.Descendants().ToList())
            {
                foreach (XAttribute attr in element.Attributes().ToList())
                {
                    if (attr.IsNamespaceDeclaration) continue;
                    string value = attr.Value;
                    if (!Regex.IsMatch(value, "^on_[A-Za-z0-9_]+$")) continue;

                    string name = (string)element.Attribute(X + "Name") ?? (string)element.Attribute("Name");
                    if (string.IsNullOrEmpty(name))
                    {
                        name = "fmHook" + (counter++);
                        element.SetAttributeValue(X + "Name", name);
                    }
                    hooks.Add(new Hook { ElementName = name, Event = attr.Name.LocalName, Handler = value });
                    attr.Remove();
                }
            }

            object loaded;
            using (var reader = XmlReader.Create(new StringReader(doc.ToString(SaveOptions.DisableFormatting))))
                loaded = XamlReader.Load(reader);

            var root = loaded as T;
            if (root == null) throw new InvalidCastException(fileName + " is not a " + typeof(T).Name);

            foreach (Hook hook in hooks)
            {
                try { Wire(root, owner, hook); }
                catch (Exception ex) { throw new InvalidOperationException("could not wire " + hook.Handler + " (" + hook.Event + ") in " + fileName + ": " + ex.Message, ex); }
            }
            return root;
        }

        private static string Normalise(string s) { return s.Replace("_", "").ToLowerInvariant(); }

        private static void Wire(FrameworkElement root, object owner, Hook hook)
        {
            object target = hook.ElementName == null ? root : root.FindName(hook.ElementName);
            if (target == null) throw new InvalidOperationException("no element named " + hook.ElementName);

            string wanted = Normalise(hook.Handler);
            MethodInfo method = null;
            for (Type t = owner.GetType(); t != null && method == null; t = t.BaseType)
            {
                method = t.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                    .FirstOrDefault(m => Normalise(m.Name) == wanted && m.GetParameters().Length == 2);
            }
            if (method == null) throw new MissingMethodException(owner.GetType().Name, hook.Handler);

            EventInfo ev = FindEvent(target.GetType(), hook.Event);
            if (ev == null) throw new MissingMemberException(target.GetType().Name, hook.Event);

            ev.AddEventHandler(target, MakeGuarded(ev.EventHandlerType, owner, method, hook.Handler));
        }

        private static EventInfo FindEvent(Type type, string name)
        {
            for (Type t = type; t != null; t = t.BaseType)
            {
                EventInfo ev = t.GetEvent(name, BindingFlags.Instance | BindingFlags.Public);
                if (ev != null) return ev;
            }
            return null;
        }

        private static readonly MethodInfo DispatchMethod = typeof(FmXaml).GetMethod("Dispatch", BindingFlags.Static | BindingFlags.NonPublic);

        /// <summary>A delegate of the event's own type that calls the owner's method inside a guard.</summary>
        private static Delegate MakeGuarded(Type handlerType, object owner, MethodInfo method, string name)
        {
            MethodInfo invoke = handlerType.GetMethod("Invoke");
            ParameterExpression[] ps = invoke.GetParameters().Select(p => Expression.Parameter(p.ParameterType)).ToArray();
            Expression call = Expression.Call(DispatchMethod,
                Expression.Constant(owner), Expression.Constant(method), Expression.Constant(name),
                Expression.Convert(ps[0], typeof(object)), Expression.Convert(ps[1], typeof(object)));
            return Expression.Lambda(handlerType, call, ps).Compile();
        }

        private static void Dispatch(object owner, MethodInfo method, string name, object sender, object args)
        {
            try { method.Invoke(owner, new[] { sender, args }); }
            catch (Exception ex) { FmUi.Report(name, ex); }
        }
    }
}
