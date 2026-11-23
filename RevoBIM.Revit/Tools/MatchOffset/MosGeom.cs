using System;

namespace RevoBIM.Tools.MatchOffset
{
    /// <summary>A point as plain numbers, so the geometry here runs without Revit.</summary>
    public sealed class MosPt
    {
        public readonly double X, Y, Z;

        public MosPt(double x = 0.0, double y = 0.0, double z = 0.0)
        {
            X = x;
            Y = y;
            Z = z;
        }

        public override string ToString() { return "Pt(" + X.ToString("F4") + ", " + Y.ToString("F4") + ", " + Z.ToString("F4") + ")"; }
    }

    /// <summary>Where two centrelines cross in plan, as parameters along each (not clamped: outside 0 to 1 is the apparent intersection).</summary>
    public sealed class MosCrossing
    {
        public string Refusal;
        public double Ta, Tb, X, Y;
    }

    /// <summary>What the slope tool is about to do, and why: decided from numbers only.</summary>
    public sealed class MosPlan
    {
        public bool Ok;
        public string Refusal = "";
        public double? MainGradient, BranchGradient;
        public double TargetGradient, Tilt;
        public double[] Axis = { 0.0, 0.0 };
        public MosPt Crossing;
        public string MainCase = "", BranchCase = "";
        public string Junction = MosGeom.None;
        public bool ExtendsMain;
        public double PlanAngle, Ta, Tb, Lateral;
    }

    /// <summary>The two turns that put a fitting's own axes onto the ones it has to meet, and the angle the branch is left off by.</summary>
    public sealed class MosOrientation
    {
        public double[] AxisOne, AxisTwo;
        public double AngleOne, AngleTwo, Left;
    }

    /// <summary>
    /// Match Offset Slope: the geometry, with no Revit in it. The datum is the crossing point of the two centrelines
    /// in plan, not the main's mid point or either end, which is what makes it right on a sloping main. Port of mos_geom.py.
    /// </summary>
    public static class MosGeom
    {
        public const double Eps = 1e-9;
        public const double MmPerFt = 304.8;

        public const string Parallel = "parallel";
        public const string Vertical = "vertical";

        public const string Inside = "inside";
        public const string InLine = "in line";
        public const string AtStart = "at start";
        public const string AtEnd = "at end";
        public const string BeforeStart = "before start";
        public const string BeyondEnd = "beyond end";

        public const string Extend = "extend";
        public const string Trim = "trim";
        public const string Behind = "behind";

        public const string Towards = "towards";
        public const string Away = "away";
        public const string KeepDirection = "keep";
        public const string FromMain = "main";
        public const string Fixed = "fixed";
        public const string KeepSlope = "keep";

        public const string Tee = "tee";
        public const string Bend = "bend";
        public const string Union = "union";
        public const string None = "none";

        public const int UpstreamFirst = 0, UpstreamSecond = 1, UpstreamUnknown = -1;

        // ======================================================================
        // lengths, directions and gradients
        // ======================================================================

        public static double PlanLength(MosPt a, MosPt b) { return Math.Sqrt((b.X - a.X) * (b.X - a.X) + (b.Y - a.Y) * (b.Y - a.Y)); }

        public static double Length(MosPt a, MosPt b)
        {
            return Math.Sqrt((b.X - a.X) * (b.X - a.X) + (b.Y - a.Y) * (b.Y - a.Y) + (b.Z - a.Z) * (b.Z - a.Z));
        }

        /// <summary>Unit direction in plan from a to b, or null for a vertical line.</summary>
        public static double[] PlanDirection(MosPt a, MosPt b)
        {
            double dx = b.X - a.X, dy = b.Y - a.Y;
            double run = Math.Sqrt(dx * dx + dy * dy);
            if (run < Eps) return null;
            return new[] { dx / run, dy / run };
        }

        /// <summary>Rise over plan run, signed along a to b. Null when there is no run.</summary>
        public static double? Gradient(MosPt a, MosPt b)
        {
            double run = PlanLength(a, b);
            if (run < Eps) return null;
            return (b.Z - a.Z) / run;
        }

        /// <summary>How far off level a segment is, always positive.</summary>
        public static double PitchDegrees(MosPt a, MosPt b)
        {
            double run = PlanLength(a, b);
            double rise = Math.Abs(b.Z - a.Z);
            if (run < Eps) return rise > Eps ? 90.0 : 0.0;
            return Math.Atan2(rise, run) * 180.0 / Math.PI;
        }

        /// <summary>A gradient as the number plumbers use. Null for level.</summary>
        public static double? OneInN(double? grad)
        {
            if (!grad.HasValue || Math.Abs(grad.Value) < 1e-7) return null;
            return 1.0 / Math.Abs(grad.Value);
        }

        /// <summary>1 in N back to a gradient magnitude. A silly N is treated as level.</summary>
        public static double GradientFromN(double n)
        {
            if (Math.Abs(n) < 1.0) return 0.0;
            return 1.0 / Math.Abs(n);
        }

        /// <summary>The angle between two plan directions, 0 to 180 degrees.</summary>
        public static double PlanAngleBetween(double[] v1, double[] v2)
        {
            if (v1 == null || v2 == null) return 90.0;
            double dot = Math.Max(-1.0, Math.Min(1.0, v1[0] * v2[0] + v1[1] * v2[1]));
            return Math.Acos(dot) * 180.0 / Math.PI;
        }

        /// <summary>Two directions that are the same line, either way round.</summary>
        public static bool IsInLine(double[] v1, double[] v2, double toleranceDeg = 2.0)
        {
            double angle = PlanAngleBetween(v1, v2);
            return angle <= toleranceDeg || angle >= 180.0 - toleranceDeg;
        }

        // ======================================================================
        // where the two centrelines cross, in plan
        // ======================================================================

        public static MosCrossing PlanIntersection(MosPt a0, MosPt a1, MosPt b0, MosPt b1)
        {
            double ax = a1.X - a0.X, ay = a1.Y - a0.Y;
            double bx = b1.X - b0.X, by = b1.Y - b0.Y;
            if (Math.Sqrt(ax * ax + ay * ay) < Eps) return new MosCrossing { Refusal = Vertical };
            if (Math.Sqrt(bx * bx + by * by) < Eps) return new MosCrossing { Refusal = Vertical };

            double denominator = ax * by - ay * bx;
            if (Math.Abs(denominator) < 1e-12) return new MosCrossing { Refusal = Parallel };

            double dx = b0.X - a0.X, dy = b0.Y - a0.Y;
            double ta = (dx * by - dy * bx) / denominator;
            double tb = (dx * ay - dy * ax) / denominator;
            return new MosCrossing { Ta = ta, Tb = tb, X = a0.X + ax * ta, Y = a0.Y + ay * ta };
        }

        /// <summary>How far a point sits off a line, measured in plan. Two runs meant to be one are rarely on one line to the millimetre.</summary>
        public static double? LateralOffset(MosPt a0, MosPt a1, MosPt point)
        {
            double[] direction = PlanDirection(a0, a1);
            if (direction == null) return null;
            return Math.Abs((point.X - a0.X) * -direction[1] + (point.Y - a0.Y) * direction[0]);
        }

        /// <summary>Where a point falls along a line in plan, as a fraction of it.</summary>
        public static double? ParameterAlong(MosPt a0, MosPt a1, MosPt point)
        {
            double run = PlanLength(a0, a1);
            if (run < Eps) return null;
            double[] direction = PlanDirection(a0, a1);
            return ((point.X - a0.X) * direction[0] + (point.Y - a0.Y) * direction[1]) / run;
        }

        /// <summary>Which end of a line a point is nearest, in plan.</summary>
        public static MosPt NearerEnd(MosPt a0, MosPt a1, MosPt point)
        {
            return PlanLength(a0, point) <= PlanLength(a1, point) ? a0 : a1;
        }

        /// <summary>The 3D point at parameter t along a line, extrapolated freely (past 1 is the main's fall carried on).</summary>
        public static MosPt PointOnLine(MosPt a0, MosPt a1, double t)
        {
            return new MosPt(a0.X + (a1.X - a0.X) * t, a0.Y + (a1.Y - a0.Y) * t, a0.Z + (a1.Z - a0.Z) * t);
        }

        // ======================================================================
        // what kind of junction this is
        // ======================================================================

        /// <summary>Where along the main the crossing falls. An end tolerance, because a crossing a millimetre inside the end is a bend in anybody's drawing.</summary>
        public static string ClassifyMain(double ta, double mainPlanLength, double endToleranceFt)
        {
            if (mainPlanLength < Eps) return Vertical;
            double slack = endToleranceFt / mainPlanLength;
            if (ta < -slack) return BeforeStart;
            if (ta > 1.0 + slack) return BeyondEnd;
            if (ta <= slack) return AtStart;
            if (ta >= 1.0 - slack) return AtEnd;
            return Inside;
        }

        /// <summary>What the branch has to do to reach the crossing: stretch out to it, trim back to it, or nothing sensible (it points away).</summary>
        public static string ClassifyBranch(double tb, double endToleranceFt, double branchPlanLength)
        {
            if (branchPlanLength < Eps) return Vertical;
            double slack = endToleranceFt / branchPlanLength;
            if (tb <= slack) return Behind;
            if (tb >= 1.0 - slack) return Extend;
            return Trim;
        }

        // ======================================================================
        // the gradient the branch is put on
        // ======================================================================

        /// <summary>
        /// The gradient the branch's horizontal run is put on, along anchor to free end. Negative means falling towards
        /// the junction, which is what drainage wants. "keep" hands back the branch's own gradient.
        /// </summary>
        public static double TargetGradient(double? mainGradient, double? branchGradient, string source, string direction, double fixedN)
        {
            if (source == KeepSlope) return branchGradient ?? 0.0;
            double size = source == Fixed ? GradientFromN(fixedN) : (mainGradient.HasValue ? Math.Abs(mainGradient.Value) : 0.0);
            if (direction == Away) return size;
            if (direction == KeepDirection) return branchGradient.HasValue && branchGradient.Value > 0 ? size : -size;
            return -size;
        }

        /// <summary>The gradient a run has to be on to carry another one on: two pipes made into one run fall the same way along the same line.</summary>
        public static double InLineGradient(double? mainGradient, bool sameWay, string source, double? branchGradient, double fixedN)
        {
            if (source == KeepSlope) return branchGradient ?? 0.0;
            double size;
            if (source == Fixed)
            {
                size = GradientFromN(fixedN);
                if (mainGradient.HasValue && mainGradient.Value < 0) size = -size;
            }
            else size = mainGradient ?? 0.0;
            return sameWay ? size : -size;
        }

        /// <summary>The rotation that turns one gradient into another: atan(now) minus atan(target), the sign that is easy to get backwards.</summary>
        public static double TiltAngle(double? now, double target) { return Math.Atan(now ?? 0.0) - Math.Atan(target); }

        /// <summary>z cross v, for a plan direction v.</summary>
        public static double[] TiltAxis(double[] v)
        {
            if (v == null) return new[] { 0.0, 0.0 };
            return new[] { -v[1], v[0] };
        }

        // ======================================================================
        // stretching the end pipe along its own axis
        // ======================================================================

        /// <summary>The point on a ray whose plan position is the crossing point. Only the plan distance is solved for; the height falls out.</summary>
        public static MosPt StretchToPlanPoint(MosPt fixedEnd, double[] direction3, double targetX, double targetY)
        {
            double dx = direction3[0], dy = direction3[1], dz = direction3[2];
            double run = Math.Sqrt(dx * dx + dy * dy);
            if (run < Eps) return null;
            double travel = ((targetX - fixedEnd.X) * dx + (targetY - fixedEnd.Y) * dy) / run;
            if (Math.Abs(travel) < Eps) return null;
            double scale = travel / run;
            return new MosPt(fixedEnd.X + dx * scale, fixedEnd.Y + dy * scale, fixedEnd.Z + dz * scale);
        }

        public static double[] Unit3(MosPt a, MosPt b)
        {
            double dx = b.X - a.X, dy = b.Y - a.Y, dz = b.Z - a.Z;
            double size = Math.Sqrt(dx * dx + dy * dy + dz * dz);
            if (size < Eps) return null;
            return new[] { dx / size, dy / size, dz / size };
        }

        // ======================================================================
        // 3D vectors, for orienting a fitting by hand
        // ======================================================================
        // Revit refuses NewTeeFitting whenever the branch is not square to the run, so an angled junction has to be
        // placed as a family instance and turned onto the three directions by hand.

        public static double Dot(double[] u, double[] v) { return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]; }

        public static double[] Cross(double[] u, double[] v)
        {
            return new[] { u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0] };
        }

        public static double Size(double[] u) { return Math.Sqrt(Dot(u, u)); }

        public static double[] UnitOf(double[] u)
        {
            double size = Size(u);
            if (size < Eps) return null;
            return new[] { u[0] / size, u[1] / size, u[2] / size };
        }

        public static double[] Scale(double[] u, double factor) { return new[] { u[0] * factor, u[1] * factor, u[2] * factor }; }
        public static double[] Add(double[] u, double[] v) { return new[] { u[0] + v[0], u[1] + v[1], u[2] + v[2] }; }

        /// <summary>The angle between two directions, 0 to 180 degrees.</summary>
        public static double AngleBetween(double[] u, double[] v)
        {
            double[] a = u == null ? null : UnitOf(u), b = v == null ? null : UnitOf(v);
            if (a == null || b == null) return 0.0;
            return Math.Acos(Math.Max(-1.0, Math.Min(1.0, Dot(a, b)))) * 180.0 / Math.PI;
        }

        /// <summary>Rodrigues, in full: the axis here is not flat.</summary>
        public static double[] RotateVector(double[] u, double[] axis, double angle)
        {
            double[] k = UnitOf(axis);
            if (k == null || Math.Abs(angle) < Eps) return u;
            double cos = Math.Cos(angle), sin = Math.Sin(angle);
            return Add(Add(Scale(u, cos), Scale(Cross(k, u), sin)), Scale(k, Dot(k, u) * (1.0 - cos)));
        }

        /// <summary>
        /// The axis and angle that turn direction u onto direction v. Where the two are already opposite the cross
        /// product is nothing and any perpendicular axis will do, so one is made.
        /// </summary>
        public static double[] RotationTo(double[] u, double[] v, out double angle)
        {
            double[] a = u == null ? null : UnitOf(u), b = v == null ? null : UnitOf(v);
            angle = 0.0;
            if (a == null || b == null) return null;
            double dot = Math.Max(-1.0, Math.Min(1.0, Dot(a, b)));
            if (dot > 1.0 - 1e-12) return new[] { 0.0, 0.0, 1.0 };
            double[] axis = UnitOf(Cross(a, b));
            if (axis == null)
            {
                axis = UnitOf(Cross(a, new[] { 0.0, 0.0, 1.0 })) ?? UnitOf(Cross(a, new[] { 0.0, 1.0, 0.0 }));
                angle = Math.PI;
                return axis;
            }
            angle = Math.Acos(dot);
            return axis;
        }

        /// <summary>The angle about a given axis that best takes u onto v (both flattened onto the plane square to the axis first).</summary>
        public static double SpinAngle(double[] u, double[] v, double[] about)
        {
            double[] k = UnitOf(about);
            if (k == null) return 0.0;
            double[] flatU = UnitOf(Add(u, Scale(k, -Dot(k, u))));
            double[] flatV = UnitOf(Add(v, Scale(k, -Dot(k, v))));
            if (flatU == null || flatV == null) return 0.0;
            double angle = Math.Acos(Math.Max(-1.0, Math.Min(1.0, Dot(flatU, flatV))));
            if (Dot(k, Cross(flatU, flatV)) < 0) angle = -angle;
            return angle;
        }

        /// <summary>
        /// Two turns that put a fitting's own axes onto the ones it has to meet: first swing the run axis onto the
        /// main, then spin about the main until the branch axis lines up.
        /// </summary>
        public static MosOrientation OrientationFor(double[] fromRun, double[] fromBranch, double[] toRun, double[] toBranch)
        {
            var result = new MosOrientation();
            double angleOne;
            result.AxisOne = RotationTo(fromRun, toRun, out angleOne);
            result.AngleOne = angleOne;
            double[] branch = result.AxisOne != null ? RotateVector(fromBranch, result.AxisOne, angleOne) : fromBranch;
            result.AxisTwo = UnitOf(toRun);
            result.AngleTwo = SpinAngle(branch, toBranch, result.AxisTwo);
            double[] left = RotateVector(branch, result.AxisTwo, result.AngleTwo);
            result.Left = AngleBetween(left, toBranch);
            return result;
        }

        /// <summary>
        /// Where to put a square tee and a bend so an angled branch can meet it: the tee slides along the main, a short
        /// stub runs square out of it, a bend turns the branch into the stub. Returns false when the branch is in line.
        /// </summary>
        public static bool SquareJunction(MosPt crossing, double[] mainDir, double[] branchDir, double stub, out MosPt tee, out MosPt bend)
        {
            double along = Dot(mainDir, branchDir);
            double[] across = Add(branchDir, Scale(mainDir, -along));
            double size = Size(across);
            tee = bend = null;
            if (size < 1e-9) return false;
            double reach = stub / size;
            tee = new MosPt(crossing.X + mainDir[0] * (-along * reach), crossing.Y + mainDir[1] * (-along * reach),
                            crossing.Z + mainDir[2] * (-along * reach));
            bend = new MosPt(crossing.X - branchDir[0] * reach, crossing.Y - branchDir[1] * reach, crossing.Z - branchDir[2] * reach);
            return true;
        }

        /// <summary>Which of a main's two ends water comes from: the higher one. A level main has no answer.</summary>
        public static int UpstreamOf(MosPt firstEnd, MosPt secondEnd, double toleranceFt = 1e-6)
        {
            if (Math.Abs(firstEnd.Z - secondEnd.Z) <= toleranceFt) return UpstreamUnknown;
            return firstEnd.Z > secondEnd.Z ? UpstreamFirst : UpstreamSecond;
        }

        /// <summary>
        /// Whether a swept junction placed this way round faces the flow: its arm leans back towards where the water
        /// comes from, so it makes the acute angle with the run connector on the upstream side.
        /// </summary>
        public static bool SweepsWithTheFlow(double runToBranchAngle, bool runIsUpstream)
        {
            bool acute = runToBranchAngle <= 90.0;
            return acute == runIsUpstream;
        }

        /// <summary>Whether the branch is already heading downstream when it arrives (one arriving against the flow cannot be swept in).</summary>
        public static bool BranchArrivesWithTheFlow(double[] mainDir, double[] branchDir) { return Dot(mainDir, branchDir) > 0; }

        /// <summary>Where two lines meet, or the middle of where they come nearest.</summary>
        public static MosPt ClosestPointBetween(MosPt p1, double[] d1, MosPt p2, double[] d2)
        {
            double[] u = d1 == null ? null : UnitOf(d1), v = d2 == null ? null : UnitOf(d2);
            if (u == null || v == null) return p1;
            double[] w0 = { p1.X - p2.X, p1.Y - p2.Y, p1.Z - p2.Z };
            double a = Dot(u, u), b = Dot(u, v), c = Dot(v, v);
            double d = Dot(u, w0), e = Dot(v, w0);
            double denominator = a * c - b * b;
            if (Math.Abs(denominator) < 1e-10) return p1;
            double s = (b * e - c * d) / denominator;
            double t = (a * e - b * d) / denominator;
            double[] first = { p1.X + u[0] * s, p1.Y + u[1] * s, p1.Z + u[2] * s };
            double[] second = { p2.X + v[0] * t, p2.Y + v[1] * t, p2.Z + v[2] * t };
            return new MosPt((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0, (first[2] + second[2]) / 2.0);
        }

        // ======================================================================
        // the whole plan, worked out before anything is touched
        // ======================================================================

        /// <summary>Two runs on the same line at different heights, made into one run: the point to work to is the main's own free end.</summary>
        private static MosPlan BuildInLinePlan(MosPt mainStart, MosPt mainEnd, MosPt anchor, MosPt freeEnd, string source, double fixedN,
                                               double endToleranceFt, bool mainEndFree, double lateralToleranceFt)
        {
            var plan = new MosPlan { MainCase = InLine };
            double[] vMain = PlanDirection(mainStart, mainEnd);
            double[] vBranch = PlanDirection(anchor, freeEnd);
            plan.PlanAngle = PlanAngleBetween(vMain, vBranch);

            double off = Math.Max(LateralOffset(mainStart, mainEnd, anchor) ?? 0.0, LateralOffset(mainStart, mainEnd, freeEnd) ?? 0.0);
            plan.Lateral = off;
            if (off > lateralToleranceFt)
            {
                plan.Refusal = "side by side";
                return plan;
            }
            if (!mainEndFree)
            {
                plan.Refusal = "main end connected";
                return plan;
            }

            MosPt meeting = NearerEnd(mainStart, mainEnd, freeEnd);
            plan.Crossing = new MosPt(meeting.X, meeting.Y, meeting.Z);
            plan.Ta = ReferenceEquals(meeting, mainStart) ? 0.0 : 1.0;

            double branchRun = PlanLength(anchor, freeEnd);
            double? tb = ParameterAlong(anchor, freeEnd, plan.Crossing);
            if (!tb.HasValue)
            {
                plan.Refusal = Vertical;
                return plan;
            }
            plan.Tb = tb.Value;
            plan.BranchCase = ClassifyBranch(tb.Value, endToleranceFt, branchRun);
            if (plan.BranchCase == Behind)
            {
                plan.Refusal = Behind;
                return plan;
            }

            plan.MainGradient = Gradient(mainStart, mainEnd);
            plan.BranchGradient = Gradient(anchor, freeEnd);
            bool sameWay = (vMain != null && vBranch != null) ? (vMain[0] * vBranch[0] + vMain[1] * vBranch[1]) > 0 : true;
            plan.TargetGradient = InLineGradient(plan.MainGradient, sameWay, source, plan.BranchGradient, fixedN);
            plan.Tilt = TiltAngle(plan.BranchGradient, plan.TargetGradient);
            plan.Axis = TiltAxis(vBranch);
            plan.Junction = Union;
            plan.Ok = true;
            return plan;
        }

        /// <summary>
        /// Work the whole move out before touching the model. mainStart/mainEnd are the main's centreline;
        /// anchor/freeEnd are the branch's end pipe, oriented so freeEnd is the one that moves.
        /// </summary>
        public static MosPlan BuildPlan(MosPt mainStart, MosPt mainEnd, MosPt anchor, MosPt freeEnd, string source, string direction,
                                        double fixedN, double endToleranceFt, bool allowApparent, bool mainEndFree,
                                        double inLineToleranceDeg, bool allowInLine, double lateralToleranceFt)
        {
            var plan = new MosPlan();

            MosCrossing crossing = PlanIntersection(mainStart, mainEnd, anchor, freeEnd);
            if (crossing.Refusal != null)
            {
                // Two runs on the same line are parallel, which is the one kind of parallel worth doing something about:
                // they are meant to be one run at one fall.
                if (crossing.Refusal == Parallel && allowInLine &&
                    IsInLine(PlanDirection(mainStart, mainEnd), PlanDirection(anchor, freeEnd), inLineToleranceDeg))
                    return BuildInLinePlan(mainStart, mainEnd, anchor, freeEnd, source, fixedN, endToleranceFt, mainEndFree, lateralToleranceFt);
                plan.Refusal = crossing.Refusal;
                return plan;
            }

            plan.Ta = crossing.Ta;
            plan.Tb = crossing.Tb;
            plan.Crossing = PointOnLine(mainStart, mainEnd, plan.Ta);

            double mainRun = PlanLength(mainStart, mainEnd);
            double branchRun = PlanLength(anchor, freeEnd);
            plan.MainCase = ClassifyMain(plan.Ta, mainRun, endToleranceFt);
            plan.BranchCase = ClassifyBranch(plan.Tb, endToleranceFt, branchRun);

            double[] vMain = PlanDirection(mainStart, mainEnd);
            double[] vBranch = PlanDirection(anchor, freeEnd);
            plan.PlanAngle = PlanAngleBetween(vMain, vBranch);

            if (plan.MainCase == Vertical || plan.BranchCase == Vertical)
            {
                plan.Refusal = Vertical;
                return plan;
            }
            if (plan.BranchCase == Behind)
            {
                plan.Refusal = Behind;
                return plan;
            }

            bool beyond = plan.MainCase == BeforeStart || plan.MainCase == BeyondEnd;
            if (beyond)
            {
                if (!allowApparent)
                {
                    plan.Refusal = "apparent";
                    return plan;
                }
                if (!mainEndFree)
                {
                    plan.Refusal = "main end connected";
                    return plan;
                }
                plan.ExtendsMain = true;
            }

            plan.MainGradient = Gradient(mainStart, mainEnd);
            plan.BranchGradient = Gradient(anchor, freeEnd);
            plan.TargetGradient = TargetGradient(plan.MainGradient, plan.BranchGradient, source, direction, fixedN);
            plan.Tilt = TiltAngle(plan.BranchGradient, plan.TargetGradient);
            plan.Axis = TiltAxis(vBranch);

            if (beyond || plan.MainCase == AtStart || plan.MainCase == AtEnd)
                plan.Junction = IsInLine(vMain, vBranch, inLineToleranceDeg) ? Union : Bend;
            else plan.Junction = Tee;

            plan.Ok = true;
            return plan;
        }

        public static string RefusalText(string key)
        {
            switch (key)
            {
                case Parallel:
                    return "the two pipes are parallel in plan but not on the same line, so they never cross and cannot be made into one run";
                case "side by side":
                    return "the two runs are on nearly the same line but too far apart in plan to be joined end to end - move one onto " +
                           "the other's line first, or widen the in-line tolerance in Settings";
                case Vertical:
                    return "one of the pipes is vertical in plan - pick a horizontal run";
                case Behind:
                    return "the branch points away from the main, so the crossing is behind its own run";
                case "apparent":
                    return "the crossing falls past the end of the main, and apparent intersections are turned off in Settings";
                case "main end connected":
                    return "the crossing falls past the end of the main and that end already has something joined to it, so there is nowhere to extend it to";
                default:
                    return key;
            }
        }
    }
}
