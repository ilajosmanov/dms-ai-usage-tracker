import QtQuick
import qs.Common
import qs.Widgets
import qs.Modules.Plugins
import "Usage.js" as Usage

PluginSettings {
    pluginId: "aiUsage"
    StyledText {
        width: parent.width
        text: "AI Usage"
        color: Theme.surfaceText
        font.pixelSize: Theme.fontSizeLarge
        font.weight: Font.Medium
    }
    StyledText {
        width: parent.width
        text: "Track your subscription accounts across clients. Existing Codex, Claude Code, pi, OMP, and opencode credentials are detected automatically."
        color: Theme.surfaceVariantText
        font.pixelSize: Theme.fontSizeSmall
        wrapMode: Text.Wrap
    }
    SelectionSetting {
        settingKey: "defaultProvider"
        label: "Primary provider"
        description: "Both providers are always shown; this one takes the left column."
        defaultValue: "codex"
        options: Usage.providerOptions()
    }
    ToggleSetting {
        settingKey: "showPacing"
        label: "Show pacing"
        description: "Compare usage with elapsed time in each fixed-length window."
        defaultValue: true
    }
    SliderSetting {
        settingKey: "refreshInterval"
        label: "Refresh interval"
        description: "Automatic API refresh interval. New logins are checked every thirty seconds. Right-click or press Refresh to check usage now."
        defaultValue: 2; minimum: 2; maximum: 15; unit: "min"
    }
    StringSetting {
        settingKey: "codexAuthFile"
        label: "Codex auth file (optional)"
        placeholder: "~/.codex/auth.json"
    }
    StringSetting {
        settingKey: "claudeAuthFile"
        label: "Claude credentials file (optional)"
        placeholder: "~/.claude/.credentials.json"
    }
    StringSetting {
        settingKey: "ompDatabase"
        label: "OMP database (optional)"
        placeholder: "~/.omp/agent/agent.db"
    }
}
