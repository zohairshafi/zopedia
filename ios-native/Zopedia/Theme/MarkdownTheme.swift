@preconcurrency import MarkdownUI
import SwiftUI

extension Theme {
    /// Web-parity Markdown: primary underlined links, framed code blocks and
    /// bordered tables with a muted header row.
    @MainActor
    static let zopedia = Theme()
        .text {
            ForegroundColor(ZTheme.foreground)
        }
        .link {
            ForegroundColor(ZTheme.primary)
            UnderlineStyle(.single)
        }
        .code {
            FontFamilyVariant(.monospaced)
            FontSize(.em(0.92))
            ForegroundColor(ZTheme.foreground)
        }
        .heading1 { configuration in
            configuration.label
                .markdownMargin(top: .em(1.4), bottom: .em(0.5))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(1.6))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .heading2 { configuration in
            configuration.label
                .markdownMargin(top: .em(1.3), bottom: .em(0.4))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(1.35))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .heading3 { configuration in
            configuration.label
                .markdownMargin(top: .em(1.2), bottom: .em(0.4))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(1.17))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .heading4 { configuration in
            configuration.label
                .markdownMargin(top: .em(1.1), bottom: .em(0.3))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(1))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .heading5 { configuration in
            configuration.label
                .markdownMargin(top: .em(1), bottom: .em(0.3))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(0.92))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .heading6 { configuration in
            configuration.label
                .markdownMargin(top: .em(1), bottom: .em(0.3))
                .markdownTextStyle {
                    FontWeight(.semibold)
                    FontSize(.em(0.88))
                    ForegroundColor(ZTheme.foreground)
                }
        }
        .paragraph { configuration in
            configuration.label
                .fixedSize(horizontal: false, vertical: true)
                .relativeLineSpacing(.em(0.18))
                .markdownMargin(top: .zero, bottom: .em(0.85))
        }
        .blockquote { configuration in
            configuration.label
                .markdownTextStyle {
                    ForegroundColor(ZTheme.mutedForeground)
                }
                .padding(.leading, 12)
                .overlay(alignment: .leading) {
                    Rectangle()
                        .fill(ZTheme.border)
                        .frame(width: 3)
                }
                .markdownMargin(top: .em(0.4), bottom: .em(1))
        }
        .codeBlock { configuration in
            ScrollView(.horizontal, showsIndicators: false) {
                configuration.label
                    .fixedSize(horizontal: false, vertical: true)
                    .relativeLineSpacing(.em(0.18))
                    .markdownTextStyle {
                        FontFamilyVariant(.monospaced)
                        FontSize(.em(0.88))
                        ForegroundColor(ZTheme.codeForeground)
                    }
                    .padding(12)
            }
            .background(ZTheme.codeBlock)
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(ZTheme.codeBlockBorder, lineWidth: 1)
            }
            .markdownMargin(top: .em(0.4), bottom: .em(1))
        }
        .table { configuration in
            configuration.label
                .markdownTableBorderStyle(
                    TableBorderStyle(.insideHorizontalBorders, color: ZTheme.border, width: 1)
                )
                .markdownTableBackgroundStyle(
                    TableBackgroundStyle { row, _ in
                        row == 0 ? ZTheme.muted.opacity(0.8) : Color.clear
                    }
                )
                .padding(8)
                .background(ZTheme.sidebar)
                .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .stroke(ZTheme.border, lineWidth: 1)
                }
                .markdownMargin(top: .em(0.5), bottom: .em(1))
        }
        .tableCell { configuration in
            configuration.label
                .markdownTextStyle {
                    if configuration.row == 0 {
                        FontWeight(.semibold)
                    }
                    FontSize(.em(0.88))
                    ForegroundColor(ZTheme.foreground)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .fixedSize(horizontal: false, vertical: true)
        }
        .thematicBreak {
            Divider()
                .overlay(ZTheme.border)
                .markdownMargin(top: .em(1.5), bottom: .em(1.5))
        }
}
