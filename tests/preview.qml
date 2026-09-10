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
    property var names: ["dashboard", "accounts", "missing", "stale", "narrow", "light", "bar", "vertical", "bar_codex", "bar_claude", "bar_over", "bar_idle", "bar_missing", "bar_light"]
    readonly property bool isBarStage: stage >= 6
    AIUsageSettings { width: 400; visible: false }

    // Walk `data`, not `children`: a Popup such as a tooltip is a non-visual
    // child and never appears in the visual children list.
    function findNamed(item, name) {
        if (!item) return null;
        if (item.objectName === name) return item;
        var pool = item.data !== undefined ? item.data : item.children;
        if (pool === undefined) return null;
        for (var i = 0; i < pool.length; i++) {
            var found = preview.findNamed(pool[i], name);
            if (found) return found;
        }
        return null;
    }
    function column(provider) {
        var found = preview.findNamed(dashboard, "providerColumn-" + provider);
        if (!found) throw new Error("Both providers must be on screen at once; missing " + provider);
        return found;
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
        implicitWidth: 440
        implicitHeight: 560
        color: Theme.surface
        Rectangle {
            id: frame
            width: preview.stage === 7 ? 120 : preview.isBarStage ? 240 : 440
            height: preview.stage === 7 ? 120 : preview.isBarStage ? 64
                : preview.stage === 4 ? 300 : Math.ceil(dashboard.implicitHeight) + 16
            color: Theme.surface
            UsageDashboard {
                id: dashboard
                x: 8; y: 8
                visible: !preview.isBarStage
                width: parent.width - 16
                snapshot: preview.data
                maxBodyHeight: preview.stage === 4 ? 190 : 1000
                closePopout: () => preview.closeRequests++
                onDashboardRequested: url => preview.openedUrl = url
            }
            AIUsagePill {
                id: pill
                visible: preview.isBarStage
                anchors.centerIn: parent
                snapshot: preview.data
                vertical: preview.stage === 7
            }
        }
    }
    Timer {
        id: capture
        interval: 800
        repeat: false
        onTriggered: {
            if (!preview.isBarStage) {
                var codexColumn = preview.column("codex");
                var claudeColumn = preview.column("claude");
                if (codexColumn.x >= claudeColumn.x)
                    throw new Error("The primary provider must take the left column");
                if (Math.abs(codexColumn.width - claudeColumn.width) > 1)
                    throw new Error("Both columns must be the same width");
                var refresh = preview.findNamed(dashboard, "refreshButton");
                var updated = preview.findNamed(dashboard, "updatedLabel");
                if (!updated.visible || updated.text === "")
                    throw new Error("Header must show update status");
                if (preview.findNamed(dashboard, "usageHeader") === null)
                    throw new Error("Header must stay outside the scrolling body");
                for (var p = 0; p < 2; p++) {
                    var provider = ["codex", "claude"][p];
                    var link = preview.findNamed(dashboard, "dashboardButton-" + provider);
                    if (!link) throw new Error("Each column needs its own dashboard action: " + provider);
                    if (link.text !== "" || link.contentItem.name !== "open_in_new")
                        throw new Error("Dashboard action must be icon-only");
                    if (preview.stage === 0) {
                        var closesBefore = preview.closeRequests;
                        link.clicked();
                        if (preview.closeRequests !== closesBefore + 1)
                            throw new Error("Dashboard action must close the dialog");
                        if (preview.openedUrl !== Usage.dashboardUrl(provider))
                            throw new Error("Each column must open its own provider's dashboard");
                    }
                }
                if (preview.stage === 4) {
                    var scroll = preview.findNamed(dashboard, "usageScroll");
                    var yBefore = refresh.mapToItem(dashboard, 0, 0).y;
                    scroll.contentY = scroll.contentHeight - scroll.height;
                    if (refresh.mapToItem(dashboard, 0, 0).y !== yBefore || updated.mapToItem(dashboard, 0, 0).y > scroll.y)
                        throw new Error("Header actions and update time must remain fixed while scrolling");
                    scroll.contentY = 0;
                }
            }
            if (preview.stage === 0) {
                if (preview.findNamed(dashboard, "columnTitle-codex").text !== "Codex"
                    || preview.findNamed(dashboard, "columnPlan-codex").text !== "Pro")
                    throw new Error("Each column names its own subscription and plan");
                var busiest = preview.findNamed(dashboard, "modelName-codex-0");
                var busiestTokens = preview.findNamed(dashboard, "modelTokens-codex-0");
                if (!busiest || busiest.text !== "GPT-5.6 Sol" || busiestTokens.text !== "1.6B")
                    throw new Error("The models block must lead with the busiest model: "
                        + (busiest ? busiest.text + " " + busiestTokens.text : "missing block"));
                var widest = preview.findNamed(dashboard, "modelBarFill-codex-0");
                var narrower = preview.findNamed(dashboard, "modelBarFill-codex-1");
                if (!(widest.width > narrower.width))
                    throw new Error("Model bars must be proportional to their token totals");
                if (preview.findNamed(dashboard, "modelName-claude-0").text !== "Claude Opus 5")
                    throw new Error("Each column lists its own provider's models");
                var codexFill = preview.findNamed(dashboard, "limitFill-codex-0");
                var claudeFill = preview.findNamed(dashboard, "limitFill-claude-0");
                if (String(codexFill.color) === String(claudeFill.color))
                    throw new Error("Each column keeps its own brand fill");
                if (!(claudeFill.width > codexFill.width))
                    throw new Error("Limit fills must be proportional to their own quota");
                var tick = preview.findNamed(dashboard, "paceTick-codex-0");
                if (!tick.visible || tick.x <= 0)
                    throw new Error("A fixed-length window must mark its elapsed pace");
            }
            if (preview.stage === 1) {
                var selector = preview.findNamed(dashboard, "accountSelector-codex");
                if (!selector || !selector.visible)
                    throw new Error("A provider with two accounts needs its own selector");
                if (preview.findNamed(dashboard, "accountSelector-claude").visible)
                    throw new Error("A single-account provider must not show a selector");
                if (preview.column("codex").account.id !== "codex-demo-2")
                    throw new Error("The column must open on its highest-usage account");
                selector.valueChanged("Codex · account 1");
                if (preview.column("codex").account.id !== "codex-demo")
                    throw new Error("The account selector must switch accounts");
                var fresh = JSON.parse(JSON.stringify(preview.data));
                fresh.accounts[0].windows[0].used = 40;
                preview.data = fresh;
                if (preview.column("codex").account.id !== "codex-demo"
                    || preview.column("codex").windows[0].used !== 40)
                    throw new Error("Refresh must preserve account selection");
                if (preview.column("claude").account.id !== "claude-demo")
                    throw new Error("One provider's selection must not disturb the other");
                selector.valueChanged("Codex · account 2");
                if (preview.column("codex").account.id !== "codex-demo-2")
                    throw new Error("The account selector must switch back");
            }
            if (preview.stage === 2) {
                if (!preview.findNamed(dashboard, "statusCard-codex").visible)
                    throw new Error("A disconnected provider must say so in its own column");
                if (preview.findNamed(dashboard, "statusCard-claude").visible)
                    throw new Error("A healthy provider must not inherit the other's status");
                if (!preview.findNamed(dashboard, "limitFill-claude-0"))
                    throw new Error("A healthy column keeps its limits while the other is missing");
            }
            if (preview.isBarStage) {
                if (pill.Accessible.name !== "AI Usage")
                    throw new Error("Bar must be titled AI Usage");
                if (pill.codex.provider !== "codex" || pill.claude.provider !== "claude")
                    throw new Error("The pill must receive both providers");
                var bars = preview.findNamed(pill, "usageBars");
                if (!bars) throw new Error("The pill must draw its twin bars");
                if (preview.stage === 6) {
                    var codexBar = preview.findNamed(pill, "usageBarFill-codex");
                    var claudeBar = preview.findNamed(pill, "usageBarFill-claude");
                    if (!codexBar || !claudeBar)
                        throw new Error("Every metered provider needs its own bar");
                    if (!(claudeBar.height > codexBar.height))
                        throw new Error("Bar height must follow each provider's own utilization");
                    if (String(codexBar.color) === String(claudeBar.color))
                        throw new Error("Bars keep their brand colors");
                }
                if (preview.stage === 7 || preview.stage === 8 || preview.stage === 9 || preview.stage === 11) {
                    if (pill.meters.length !== 2)
                        throw new Error("Both providers must remain in the panel when usage resets to zero");
                    pill.meters.forEach(function(account) {
                        if (Usage.primaryUsage(account) !== 0) return;
                        var track = preview.findNamed(pill, "usageBar-" + account.provider);
                        var fill = preview.findNamed(pill, "usageBarFill-" + account.provider);
                        var label = preview.findNamed(pill, "barPercent-" + account.provider);
                        if (!track || !track.visible || track.width <= 0 || track.height <= 0
                            || !label || !label.visible || label.text !== "0%")
                            throw new Error("An idle provider must keep its visible track and 0% label");
                        if (!fill || fill.height !== 0)
                            throw new Error("Zero usage must leave the track empty");
                    });
                }
                if (preview.stage === 10 || preview.stage === 13) {
                    if (pill.overPaceCount !== 2)
                        throw new Error("Both providers must have independent pace arrows");
                    if (!preview.findNamed(pill, "paceArrow-codex").visible || !preview.findNamed(pill, "paceArrow-claude").visible)
                        throw new Error("Both colored arrows must be rendered");
                    pill.showPacing = false;
                    if (pill.overPaceCount !== 0)
                        throw new Error("Pacing setting must hide bar arrows");
                    pill.showPacing = true;
                }
                if (preview.stage === 12 && pill.meters.length !== 0)
                    throw new Error("Missing usage must not show percentages");
            }
            if (preview.stage === 0) {
                // A cursor the offscreen platform cannot move, stubbed in the
                // shape HoverHandler reports. Checked in `settle`, once the
                // popup has been laid out and positioned.
                preview.openTooltip("limit-codex-0", 40);
                preview.openTooltip("limit-claude-1", 74);
            }
            settle.start();
        }
    }
    // Opens one tooltip where there is room to the right of the cursor and one
    // where there is not, so both the plain and the flipped placement are
    // covered. Returns the tooltip left open for the screenshot.
    function openTooltip(rowName, cursorX) {
        var tip = preview.findNamed(dashboard, rowName.replace("limit-", "limitTooltip-"));
        var row = preview.findNamed(dashboard, rowName);
        if (!tip || !row) throw new Error("Every limit row needs a tooltip: " + rowName);
        tip.pointer = {hovered: true, point: {position: Qt.point(cursorX, 16)}};
        tip.delay = 0;
        tip.visible = true;
        return tip;
    }
    function checkTooltip(rowName, cursorX) {
        var tip = preview.findNamed(dashboard, rowName.replace("limit-", "limitTooltip-"));
        var row = preview.findNamed(dashboard, rowName);
        if (tip.width > 260 || tip.height > 44)
            throw new Error("The tooltip must stay small: " + tip.width + "x" + tip.height);
        // Scene coordinates, because an Item popup is reparented into the
        // window's popup layer while its own x/y stay row-relative.
        var cursor = row.mapToItem(null, cursorX, 16);
        var box = tip.contentItem.mapToItem(null, 0, 0);
        var dx = Math.max(box.x - cursor.x, cursor.x - (box.x + tip.width), 0);
        var dy = Math.max(box.y - cursor.y, cursor.y - (box.y + tip.height), 0);
        if (dx > 24 || dy > 24)
            throw new Error("The tooltip must open beside the pointer, not the row: gap " + dx + "," + dy);
        if (box.x < 0 || box.x + tip.width > window.width || box.y < 0)
            throw new Error("The tooltip must stay inside the popout: " + box.x + "+" + tip.width);
        // A popup renders in the window overlay, so it never reaches the
        // frame's grab; close it and leave the state's screenshot clean.
        tip.visible = false;
    }
    Timer {
        id: settle
        interval: 150
        onTriggered: {
            if (preview.stage === 0) {
                preview.checkTooltip("limit-codex-0", 40);
                preview.checkTooltip("limit-claude-1", 74);
            }
            frame.grabToImage(function(result) {
                result.saveToFile(Quickshell.env("AI_USAGE_PREVIEW_OUT") + "/" + preview.names[preview.stage] + ".png");
                console.log("AI_USAGE_STAGE " + preview.names[preview.stage] + " " + frame.width + "x" + frame.height);
                preview.stage++;
                if (preview.stage >= preview.names.length) {
                    console.log("AI_USAGE_PREVIEW_COMPLETE");
                    Quickshell.quit();
                    return;
                }
                var data = JSON.parse(JSON.stringify(preview.originalData));
                if (preview.stage === 1) {
                    data.accounts[0].label = "Codex · account 1";
                    var second = JSON.parse(JSON.stringify(data.accounts[0]));
                    second.id = "codex-demo-2";
                    second.label = "Codex · account 2";
                    second.windows[0].used = 80;
                    second.history[second.history.length - 1].value = 80;
                    data.accounts.push(second);
                } else if (preview.stage === 2) {
                    data.accounts[0].status = "missing";
                    data.accounts[0].windows = [];
                    data.accounts[0].history = [];
                    data.accounts[0].models = [];
                    data.accounts[0].message = "Sign in with ChatGPT in your coding client. New logins are detected automatically.";
                } else if (preview.stage === 3) {
                    data.accounts[1].status = "stale";
                    data.accounts[1].message = "Provider rate limited this check.";
                    // The worst case for this card: a saved column that a manual
                    // refresh cannot move for the next hour.
                    data.accounts[1].retryAt = Date.now() / 1000 + 3300;
                    data.accounts[1].updatedAt = Date.now() / 1000 - 900;
                }
                if (preview.stage === 7 || preview.stage === 8) data.accounts[1].windows[0].used = 0;
                if (preview.stage === 9) data.accounts[0].windows[0].used = 0;
                if (preview.stage === 10 || preview.stage === 13) {
                    data.accounts.forEach(function(a) {
                        a.windows[0].used = 80;
                        a.windows[0].resetAt = Date.now() / 1000 + a.windows[0].duration * 0.8;
                    });
                }
                if (preview.stage === 11) data.accounts.forEach(function(a) { a.windows[0].used = 0; });
                if (preview.stage === 12) data.accounts.forEach(function(a) { a.windows = []; a.status = "missing"; });
                SessionData.isLightMode = preview.stage === 5 || preview.stage === 13;
                preview.data = data;
                capture.start();
            });
        }
    }
}
