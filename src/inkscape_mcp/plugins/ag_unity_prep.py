"""
AG Unity Prep Extension

Prepares SVG files for Unity UI import by flattening groups, resetting coordinates,
and optimizing for game engine performance.
"""

import inkex
from inkex import Group, PathElement, Style


class AGUnityPrep(inkex.EffectExtension):
    """Prepare SVG for Unity UI import."""

    def add_arguments(self, pars):
        pars.add_argument("--flatten_groups", type=inkex.Boolean, default=True, help="Flatten all groups")
        pars.add_argument("--reset_coordinates", type=inkex.Boolean, default=True, help="Reset document coordinates")
        pars.add_argument("--optimize_paths", type=inkex.Boolean, default=True, help="Optimize path complexity")
        pars.add_argument("--remove_metadata", type=inkex.Boolean, default=True, help="Remove Inkscape metadata")

    def effect(self):
        """Prepare SVG for Unity import."""
        flatten_groups = self.options.flatten_groups
        reset_coords = self.options.reset_coordinates
        optimize_paths = self.options.optimize_paths
        remove_metadata = self.options.remove_metadata

        # Flatten all groups if requested
        if flatten_groups:
            self._flatten_all_groups()

        # Reset coordinates to origin if requested
        if reset_coords:
            self._reset_coordinates()

        # Optimize paths if requested
        if optimize_paths:
            self._optimize_paths()

        # Remove metadata if requested
        if remove_metadata:
            self._remove_metadata()

        inkex.errormsg("SVG prepared for Unity import.")

    # A group carrying any of these cannot be dissolved without changing how its children
    # render — the effect applies to the group as a unit, not per child.
    _UNFLATTENABLE = ("clip-path", "mask", "filter")

    def _flatten_all_groups(self):
        """Flatten groups, composing each group's transform/style onto its children.

        Naively re-parenting children drops the group's ``transform``, so a
        ``<g transform="translate(300,200)">`` puts everything back at the origin. Since
        ``inkex.Layer`` subclasses ``Group``, that silently wiped layer transforms too.
        """
        groups_to_process = [elem for elem in self.svg.iter() if isinstance(elem, Group)]

        skipped = 0
        flattened = 0
        # Work outward-in reversed document order so nested groups collapse before parents.
        for group in reversed(groups_to_process):
            parent = group.getparent()
            if parent is None:
                continue
            if any(group.get(attr) for attr in self._UNFLATTENABLE) or "clip-path" in group.style:
                skipped += 1
                continue
            try:
                group_transform = group.transform
                group_style = group.style
                group_opacity = group.get("opacity")

                index = parent.index(group)
                for child in list(group):
                    # Compose parent-then-child so the child's own transform still applies
                    # in the group's coordinate system.
                    if group_transform:
                        child.transform = group_transform @ child.transform
                    if group_style:
                        # The child's own declarations win over the inherited ones.
                        merged = Style(group_style)
                        merged.update(child.style)
                        child.style = merged
                    if group_opacity is not None:
                        try:
                            child.set("opacity", str(float(group_opacity) * float(child.get("opacity", 1))))
                        except (TypeError, ValueError):
                            pass
                    parent.insert(index, child)
                    index += 1
                parent.remove(group)
                flattened += 1
            except Exception as e:
                inkex.errormsg(f"Error flattening group: {e}")

        if skipped:
            inkex.errormsg(f"Kept {skipped} group(s) that carry clip-path/mask/filter (cannot flatten safely).")
        return flattened, skipped

    def _reset_coordinates(self):
        """Reset document coordinates to origin."""
        # Get current viewBox
        viewbox = self.svg.get("viewBox")
        if viewbox:
            # Parse viewBox values
            try:
                values = [float(x) for x in viewbox.split()]
                if len(values) >= 4:
                    _x, _y, width, height = values[:4]
                    # Reset to origin
                    self.svg.set("viewBox", f"0 0 {width} {height}")
            except ValueError:
                pass

        # Reset any transforms on root element
        if self.svg.get("transform"):
            self.svg.set("transform", None)

    def _optimize_paths(self):
        """Optimize path complexity for Unity."""
        for elem in self.svg.iter():
            if isinstance(elem, PathElement):
                # Remove unnecessary style attributes that Unity doesn't need
                style_attrs_to_remove = [
                    "filter",
                    "marker",
                    "marker-start",
                    "marker-mid",
                    "marker-end",
                ]
                for attr in style_attrs_to_remove:
                    if attr in elem.style:
                        del elem.style[attr]

                # Ensure stroke-width is reasonable for UI
                if "stroke-width" in elem.style:
                    try:
                        width = float(elem.style["stroke-width"])
                        if width > 5:  # Cap maximum stroke width
                            elem.style["stroke-width"] = "2px"
                        elif width < 0.5:  # Minimum visible stroke
                            elem.style["stroke-width"] = "1px"
                    except ValueError:
                        elem.style["stroke-width"] = "1px"

    def _remove_metadata(self):
        """Remove Inkscape-specific metadata."""
        # Remove Inkscape namespace declarations
        namespaces_to_remove = ["inkscape", "sodipodi"]

        # Remove metadata elements
        for elem in self.svg.iter():
            # Remove Inkscape-specific attributes
            attrs_to_remove = []
            for attr_name in elem.attrib:
                if any(ns in attr_name for ns in namespaces_to_remove):
                    attrs_to_remove.append(attr_name)

            for attr in attrs_to_remove:
                del elem.attrib[attr]

        # Remove defs that are Inkscape-specific
        defs = self.svg.defs
        if defs is not None:
            children_to_remove = []
            for child in defs:
                if child.tag.endswith("}metadata") or "inkscape" in child.tag:
                    children_to_remove.append(child)

            for child in children_to_remove:
                defs.remove(child)


if __name__ == "__main__":
    AGUnityPrep().run()
