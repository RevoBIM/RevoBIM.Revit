using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

namespace RevoBIM.Tools.FamilyThumbnail
{
    /// <summary>Post-processing of the exported view image: crop to content, resize or square canvas, save. Port of ft_image.py.</summary>
    public static class FtImage
    {
        /// <summary>BGRA bytes of a small copy of the image, for content detection.</summary>
        private static byte[] AnalysisBuffer(Bitmap src, int aw, int ah, out int stride)
        {
            using (var small = new Bitmap(src, aw, ah))
            {
                BitmapData data = small.LockBits(new Rectangle(0, 0, aw, ah), ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
                try
                {
                    stride = Math.Abs(data.Stride);
                    var raw = new byte[stride * ah];
                    Marshal.Copy(data.Scan0, raw, 0, raw.Length);
                    return raw;
                }
                finally
                {
                    small.UnlockBits(data);
                }
            }
        }

        private static void Quality(Graphics g)
        {
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.SmoothingMode = SmoothingMode.HighQuality;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
        }

        /// <summary>
        /// Crops the exported image to its content and writes the final thumbnail. mode "resize": the crop keeps its own
        /// aspect ratio, long side = size. mode "square": a size x size canvas, content centred, the background continued
        /// row by row so a gradient background has no seams.
        /// </summary>
        public static void Process(string srcPath, string dstPath, int size, string mode, string format)
        {
            using (var src = new Bitmap(srcPath))
            {
                int w = src.Width, h = src.Height;
                int aw, ah;
                FtLogic.AnalysisSize(w, h, 256, out aw, out ah);
                int stride;
                byte[] buf = AnalysisBuffer(src, aw, ah, out stride);
                List<int[]> refs;
                int[] bbox = FtLogic.ContentBBox(buf, aw, ah, stride, out refs, 14);
                int[] crop = FtLogic.CropRect(bbox, aw, ah, w, h);
                int cx = crop[0], cy = crop[1], cw = crop[2], ch = crop[3];
                FtCore.Log("image " + w + "x" + h + " bbox=" + (bbox == null ? "none" : bbox[0] + "," + bbox[1] + "," + bbox[2] + "," + bbox[3])
                           + " crop=" + cx + "," + cy + "," + cw + "," + ch);

                Bitmap output;
                if (mode == "square")
                {
                    int side = FtLogic.SquareSide(cw, ch);
                    using (var canvas = new Bitmap(side, side, PixelFormat.Format32bppArgb))
                    {
                        using (Graphics g = Graphics.FromImage(canvas))
                        {
                            int ox = (side - cw) / 2;
                            int oy = (side - ch) / 2;
                            for (int y = 0; y < side; y++)
                            {
                                int srcRow = Math.Max(0, Math.Min(h - 1, cy + (y - oy)));
                                int[] c = FtLogic.RowBackground(refs, srcRow, h);
                                using (var brush = new SolidBrush(Color.FromArgb(255, c[0], c[1], c[2])))
                                    g.FillRectangle(brush, 0, y, side, 1);
                            }
                            g.DrawImage(src, new Rectangle(ox, oy, cw, ch), cx, cy, cw, ch, GraphicsUnit.Pixel);
                        }
                        output = new Bitmap(size, size, PixelFormat.Format32bppArgb);
                        using (Graphics g2 = Graphics.FromImage(output))
                        {
                            Quality(g2);
                            g2.DrawImage(canvas, new Rectangle(0, 0, size, size), 0, 0, side, side, GraphicsUnit.Pixel);
                        }
                    }
                }
                else
                {
                    int ow, oh;
                    FtLogic.ResizeDims(cw, ch, size, out ow, out oh);
                    output = new Bitmap(ow, oh, PixelFormat.Format32bppArgb);
                    using (Graphics g = Graphics.FromImage(output))
                    {
                        Quality(g);
                        g.DrawImage(src, new Rectangle(0, 0, ow, oh), cx, cy, cw, ch, GraphicsUnit.Pixel);
                    }
                }
                using (output)
                {
                    output.Save(dstPath, string.Equals(format, "JPG", StringComparison.OrdinalIgnoreCase) ? ImageFormat.Jpeg : ImageFormat.Png);
                }
            }
        }
    }
}
