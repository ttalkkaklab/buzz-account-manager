import SwiftUI

enum ControlTier {
    case bar, inline, compact
    var size: ControlSize {
        switch self {
        case .bar: return .large
        case .inline: return .regular
        case .compact: return .small
        }
    }
}
extension View {
    func primaryAction(_ tier: ControlTier = .inline) -> some View {
        buttonStyle(.borderedProminent).tint(.teal).controlSize(tier.size)
    }
    func secondaryAction(_ tier: ControlTier = .inline) -> some View {
        buttonStyle(.bordered).controlSize(tier.size)
    }
    func popupField() -> some View {
        pickerStyle(.menu).labelsHidden().controlSize(.regular).frame(maxWidth: .infinity, alignment: .leading)
    }
}

// SwiftUI's menu Picker retains its label-sized native bezel on macOS.
// Use the system popup directly so the visible control fills its assigned row.
struct PopupOption: Equatable {
    let id: String
    let title: String
}
struct PopupField: NSViewRepresentable {
    let title: String
    @Binding var selection: String
    let options: [PopupOption]
    @Environment(\.isEnabled) private var isEnabled

    final class Coordinator: NSObject {
        var parent: PopupField
        init(_ parent: PopupField) { self.parent = parent }
        @objc func changed(_ sender: NSPopUpButton) {
            if let id = sender.selectedItem?.representedObject as? String { parent.selection = id }
        }
    }
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeNSView(context: Context) -> NSPopUpButton {
        let button = NSPopUpButton(frame: .zero, pullsDown: false)
        button.controlSize = .regular
        button.target = context.coordinator
        button.action = #selector(Coordinator.changed(_:))
        button.setContentHuggingPriority(.defaultLow, for: .horizontal)
        return button
    }
    func updateNSView(_ button: NSPopUpButton, context: Context) {
        context.coordinator.parent = self
        let current = button.itemArray.map { PopupOption(id: $0.representedObject as? String ?? "", title: $0.title) }
        if current != options {
            button.removeAllItems()
            for option in options {
                let item = NSMenuItem(title: option.title, action: nil, keyEquivalent: "")
                item.representedObject = option.id
                button.menu?.addItem(item)
            }
        }
        button.select(button.itemArray.first { ($0.representedObject as? String) == selection })
        button.isEnabled = isEnabled
        button.setAccessibilityLabel(title)
    }
    func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSPopUpButton, context: Context) -> NSSize? {
        NSSize(width: proposal.width ?? nsView.intrinsicContentSize.width, height: 24)
    }
}
