import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Plugin
import "Plugin/Usage.js" as Usage

ShellRoot {
    id: preview
    property var data: ({accounts: []})
    property var originalData: ({accounts: []})
    property int stage: 0
    property int closeRequests: 0
    property string openedUrl: ""
    property var names: ["codex", "claude", "accounts", "missing", "stale", "narrow", "light", "bar", "vertical", "bar_codex", "bar_claude", "bar_over", "bar_idle", "bar_missing", "bar_light"]
    AIUsageSettings { width: 400; visible: false }

    function findNamed(item, name) {
        if (item.objectName === name) return item;
        for (var i = 0; i < item.children.length; i++) {
            var found = findNamed(item.children[i], name);
            if (found) return found;
        }
        return null;
    }
    Process {
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("Plugin/get-ai-usage").toString().replace("file://", "")), "--demo"]
        running: true
        stdout: StdioCollector {
            onStreamFinished: {
                preview.originalData = JSON.parse(text);
                preview.data = JSON.parse(text);
                capture.start();
            }
        }
    }
    FloatingWindow {
        id: window
        title: "AI Usage Preview"
        visible: true
        implicitWidth: 420
        implicitHeight: 1080
        color: Theme.surface
        Rectangle {
            id: frame
            width: preview.stage === 5 ? 340 : preview.stage >= 7 ? 240 : 420
            height: preview.stage === 5 ? 620 : preview.stage === 8 ? 120 : preview.stage >= 7 ? 64 : 1080
            color: Theme.surface
            UsageDashboard {
                id: dashboard
                x: 8; y: 8
                visible: preview.stage < 7
                width: parent.width - 16
                snapshot: preview.data
                maxBodyHeight: preview.stage === 5 ? 450 : 1000
                closePopout: () => preview.closeRequests++
                onDashboardRequested: url => preview.openedUrl = url
            }
            AIUsagePill {
                id: pill
                visible: preview.stage >= 7
                anchors.centerIn: parent
                snapshot: preview.data
                vertical: preview.stage === 8
            }
        }
    }
    Timer {
        id: capture
        interval: 800
        repeat: false
        onTriggered: {
            if (preview.stage < 7) {
                var link = preview.findNamed(dashboard, "dashboardButton");
                var refresh = preview.findNamed(dashboard, "refreshButton");
                var updated = preview.findNamed(dashboard, "updatedLabel");
                if (link.parent !== refresh.parent || link.x + link.width > refresh.x)
                    throw new Error("Dashboard icon must be immediately left of refresh in the header");
                if (link.text !== "" || link.contentItem.name !== "open_in_new")
                    throw new Error("Dashboard action must be icon-only");
                if (!updated.visible || updated.text === "") throw new Error("Header must show update status");
                if (preview.stage === 0 || preview.stage === 1) {
                    var closesBefore = preview.closeRequests;
                    link.clicked();
                    if (preview.closeRequests !== closesBefore + 1)
                        throw new Error("Dashboard action must close the dialog");
                    var expectedUrl = preview.stage === 0 ? "https://chatgpt.com/codex/settings/usage" : "https://claude.ai/settings/usage";
                    if (preview.openedUrl !== expectedUrl) throw new Error("Dashboard action must open the selected provider");
                }
                if (preview.stage === 5) {
                    var scroll = preview.findNamed(dashboard, "usageScroll");
                    var yBefore = link.mapToItem(dashboard, 0, 0).y;
                    scroll.contentY = scroll.contentHeight - scroll.height;
                    if (link.mapToItem(dashboard, 0, 0).y !== yBefore || updated.mapToItem(dashboard, 0, 0).y > scroll.y)
                        throw new Error("Header actions and update time must remain fixed while scrolling");
                    scroll.contentY = 0;
                }
            }
            if (preview.stage === 2) {
                if (dashboard.account.id !== "codex-demo-2")
                    throw new Error("Popout must match the bar's highest-usage account");
                var selector = preview.findNamed(dashboard, "accountSelector");
                if (!selector || !selector.visible) throw new Error("Account selector must be visible");
                selector.valueChanged("Codex · account 1");
                if (dashboard.account.id !== "codex-demo") throw new Error("Account dropdown must select first account");
                var fresh = JSON.parse(JSON.stringify(preview.data));
                fresh.accounts[0].windows[0].used = 40;
                preview.data = fresh;
                if (dashboard.account.id !== "codex-demo" || dashboard.windows[0].used !== 40)
                    throw new Error("Refresh must preserve account selection");
                selector.valueChanged("Codex · account 2");
                if (dashboard.account.id !== "codex-demo-2") throw new Error("Account dropdown must select second account");
            }
            if (preview.stage >= 7) {
                if (pill.Accessible.name !== "AI Usage") throw new Error("Bar must be titled AI Usage");
                if (pill.codex.provider !== "codex" || pill.claude.provider !== "claude")
                    throw new Error("The single ring must receive both providers");
                if (preview.stage === 9 && (pill.meters.length !== 1 || pill.meters[0].provider !== "codex"))
                    throw new Error("Only Codex should be displayed");
                if (preview.stage === 10 && (pill.meters.length !== 1 || pill.meters[0].provider !== "claude"))
                    throw new Error("Only Claude should be displayed after Codex resets");
                if (preview.stage === 11 || preview.stage === 14) {
                    if (pill.overPaceCount !== 2) throw new Error("Both providers must have independent pace arrows");
                    if (!preview.findNamed(pill, "paceArrow-codex").visible || !preview.findNamed(pill, "paceArrow-claude").visible)
                        throw new Error("Both colored arrows must be rendered");
                    pill.showPacing = false;
                    if (pill.overPaceCount !== 0) throw new Error("Pacing setting must hide bar arrows");
                    pill.showPacing = true;
                }
                if (preview.stage === 13 && pill.meters.length !== 0) throw new Error("Missing usage must not show percentages");
            } else if (preview.stage === 0) {
                if (preview.findNamed(dashboard, "subscriptionTitle").text !== "Codex · Pro")
                    throw new Error("Subscription type must be capitalized");
                var busiest = preview.findNamed(dashboard, "modelName-0");
                var busiestTokens = preview.findNamed(dashboard, "modelTokens-0");
                if (!busiest || busiest.text !== "GPT-5.6 Sol" || busiestTokens.text !== "1.6B")
                    throw new Error("The models block must lead with the busiest model: "
                        + (busiest ? busiest.text + " " + busiestTokens.text : "missing block"));
                var widest = preview.findNamed(dashboard, "modelBarFill-0");
                var narrower = preview.findNamed(dashboard, "modelBarFill-1");
                if (!(widest.width > narrower.width))
                    throw new Error("Model bars must be proportional to their token totals");
            } else if (preview.stage === 1) {
                var claudeModel = preview.findNamed(dashboard, "modelName-0");
                if (!claudeModel || claudeModel.text !== "Claude Opus 5")
                    throw new Error("Claude's models block must list Claude models");
                var tooltipText = Usage.dayTooltip(Usage.days(dashboard.account.history, dashboard.now)[6]);
                if (tooltipText.indexOf("Models") !== -1)
                    throw new Error("Model names belong in their own block, not the daily hover");
            }
            settle.start();
        }
    }
    Timer {
        id: settle
        interval: 150
        onTriggered: {
            frame.grabToImage(function(result) {
                result.saveToFile(Quickshell.env("AI_USAGE_PREVIEW_OUT") + "/" + preview.names[preview.stage] + ".png");
                preview.stage++;
                if (preview.stage >= preview.names.length) {
                    console.log("AI_USAGE_PREVIEW_COMPLETE");
                    Quickshell.quit();
                    return;
                }
                var data = JSON.parse(JSON.stringify(preview.originalData));
                dashboard.accountId = "";
                dashboard.provider = preview.stage === 1 || preview.stage === 6 ? "claude" : "codex";
                if (preview.stage === 2) {
                    data.accounts[0].label = "Codex · account 1";
                    var second = JSON.parse(JSON.stringify(data.accounts[0]));
                    second.id = "codex-demo-2";
                    second.label = "Codex · account 2";
                    second.windows[0].used = 80;
                    second.history[second.history.length - 1].value = 80;
                    data.accounts.push(second);
                } else if (preview.stage === 3) {
                    data.accounts[0].status = "missing";
                    data.accounts[0].windows = [];
                    data.accounts[0].history = [];
                    data.accounts[0].message = "Sign in with ChatGPT in your coding client. New logins are detected automatically.";
                } else if (preview.stage === 4 || preview.stage === 5) {
                    data.accounts[0].status = "stale";
                    data.accounts[0].message = "Could not reach the provider. Check your connection.";
                }
                if (preview.stage === 9) data.accounts[1].windows[0].used = 0;
                if (preview.stage === 10) data.accounts[0].windows[0].used = 0;
                if (preview.stage === 11 || preview.stage === 14) {
                    data.accounts.forEach(function(a) {
                        a.windows[0].used = 80;
                        a.windows[0].resetAt = Date.now() / 1000 + a.windows[0].duration * 0.8;
                    });
                }
                if (preview.stage === 12) data.accounts.forEach(function(a) { a.windows[0].used = 0; });
                if (preview.stage === 13) data.accounts.forEach(function(a) { a.windows = []; a.status = "missing"; });
                SessionData.isLightMode = preview.stage === 6 || preview.stage === 14;
                preview.data = data;
                capture.start();
            });
        }
    }
}
