import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// Renders the menu-bar tray icon: a stroked check-circle, black on a fully
// transparent background. macOS template images use ONLY the alpha channel —
// every opaque pixel is repainted with the menu-bar foreground colour — so the
// glyph must be the opaque part and the backdrop must be transparent. (The app
// icon is the inverse: an opaque filled square, which is why using it as a
// template painted a solid block.)

func render(size: CGFloat, to path: String) {
    let cs = CGColorSpaceCreateDeviceRGB()
    guard let ctx = CGContext(
        data: nil,
        width: Int(size),
        height: Int(size),
        bitsPerComponent: 8,
        bytesPerRow: 0,
        space: cs,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else { fatalError("no context") }

    // Transparent canvas — do not fill.
    ctx.clear(CGRect(x: 0, y: 0, width: size, height: size))

    let s = size / 36.0            // design grid is 36x36
    ctx.setStrokeColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
    ctx.setLineCap(.round)
    ctx.setLineJoin(.round)
    ctx.setLineWidth(2.6 * s)

    // Circle, inset so the stroke isn't clipped at the canvas edge.
    let inset = 2.6 * s
    ctx.strokeEllipse(in: CGRect(
        x: inset, y: inset,
        width: size - inset * 2,
        height: size - inset * 2
    ))

    // Checkmark (CoreGraphics origin is bottom-left, y grows upward).
    ctx.move(to: CGPoint(x: 11.0 * s, y: 18.6 * s))
    ctx.addLine(to: CGPoint(x: 15.8 * s, y: 13.4 * s))
    ctx.addLine(to: CGPoint(x: 25.2 * s, y: 23.4 * s))
    ctx.strokePath()

    guard let image = ctx.makeImage() else { fatalError("no image") }
    let url = URL(fileURLWithPath: path)
    guard let dest = CGImageDestinationCreateWithURL(
        url as CFURL, UTType.png.identifier as CFString, 1, nil
    ) else { fatalError("no destination") }
    CGImageDestinationAddImage(dest, image, nil)
    guard CGImageDestinationFinalize(dest) else { fatalError("write failed") }
    print("wrote \(path) at \(Int(size))x\(Int(size))")
}

let out = CommandLine.arguments[1]
render(size: 36, to: out)

// Usage:  swift scripts/make_tray_icon.swift src-tauri/icons/tray-icon.png
