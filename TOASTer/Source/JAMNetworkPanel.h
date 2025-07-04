#pragma once

#include <juce_gui_basics/juce_gui_basics.h>
#include "JAMFrameworkIntegration.h"
#include "BonjourDiscovery.h"
#include "ThunderboltNetworkDiscovery.h"
#include "WiFiNetworkDiscovery.h"

// Forward declarations
class GPUTransportController;

/**
 * JAM Framework v2 Network Panel for TOASTer
 * 
 * Replaces the old TCP-based NetworkConnectionPanel with UDP multicast
 * using JAM Framework v2, including PNBTR prediction and GPU acceleration.
 */
class JAMNetworkPanel : public juce::Component, 
                       public juce::Timer,
                       public BonjourDiscovery::Listener,
                       public ThunderboltNetworkDiscovery::Listener,
                       public WiFiNetworkDiscovery::Listener {
public:
    JAMNetworkPanel();
    ~JAMNetworkPanel() override;
    
    // Component overrides
    void paint(juce::Graphics& g) override;
    void resized() override;
    
    // Network state
    bool isConnected() const;
    int getActivePeers() const;
    double getCurrentLatency() const;
    double getCurrentThroughput() const;
    
    // Send MIDI events through JAM Framework v2
    void sendMIDIEvent(uint8_t status, uint8_t data1, uint8_t data2);
    void sendMIDIData(const uint8_t* data, size_t size);
    
    // Send transport commands through JAM Framework v2
    void sendTransportCommand(const std::string& command, uint64_t timestamp, 
                             double position = 0.0, double bpm = 120.0);

    // Configuration
    void setSessionName(const juce::String& sessionName);
    void setMulticastAddress(const juce::String& address);
    void setUDPPort(int port);
    void enablePNBTRPrediction(bool audio, bool video);
    void enableGPUAcceleration(bool enable);
    
    // Transport controller integration  
    void setTransportController(GPUTransportController* controller) { transportController = controller; }
    
    // Network status callback
    using NetworkStatusCallback = std::function<void(bool connected, int peers, const std::string& address, int port)>;
    void setNetworkStatusCallback(NetworkStatusCallback callback) { networkStatusCallback = callback; }

private:
    // JAM Framework v2 integration
    std::unique_ptr<JAMFrameworkIntegration> jamFramework;
    
    // Transport controller for bidirectional sync
    GPUTransportController* transportController = nullptr;
    
    // Network status callback
    NetworkStatusCallback networkStatusCallback;

    // UI Components
    juce::Label titleLabel;
    juce::Label statusLabel;
    juce::Label performanceLabel;
    juce::Label pnbtrStatusLabel;
    
    // Network mode selection
    juce::Label networkModeLabel;
    juce::ComboBox networkModeCombo;
    
    // Configuration controls
    juce::Label sessionLabel;
    juce::TextEditor sessionNameEditor;
    juce::Label multicastLabel;
    juce::TextEditor multicastAddressEditor;
    juce::Label portLabel;
    juce::TextEditor portEditor;
    
    // Connection controls
    juce::TextButton connectButton;
    juce::TextButton disconnectButton;
    
    // Feature toggles
    juce::ToggleButton pnbtrAudioToggle;
    juce::ToggleButton pnbtrVideoToggle;
    juce::ToggleButton burstTransmissionToggle;
    juce::ToggleButton gpuAccelerationToggle;
    
    // Discovery
    std::unique_ptr<BonjourDiscovery> bonjourDiscovery;
    std::unique_ptr<ThunderboltNetworkDiscovery> thunderboltDiscovery;
    std::unique_ptr<WiFiNetworkDiscovery> wifiDiscovery;
    
    // Performance metrics display
    juce::Label latencyLabel;
    juce::Label throughputLabel;
    juce::Label peersLabel;
    juce::Label predictionLabel;
    
    // State
    bool networkConnected = false;
    int activePeers = 0;
    double currentLatency = 0.0;
    double currentThroughput = 0.0;
    double predictionAccuracy = 0.0;
    
    // Session configuration
    juce::String currentSessionName = "TOASTer_Session";
    juce::String currentMulticastAddr = "239.255.77.77";
    int currentUDPPort = 7777;
    
    // Callbacks
    void connectButtonClicked();
    void disconnectButtonClicked();
    void sessionConfigurationChanged();
    
    // JAM Framework callbacks
    void onJAMStatusChanged(const std::string& status, bool connected);
    void onJAMPerformanceUpdate(double latency_us, double throughput_mbps, int active_peers);
    void onJAMMIDIReceived(uint8_t status, uint8_t data1, uint8_t data2, uint32_t timestamp);
    void onJAMTransportReceived(const std::string& command, uint64_t timestamp, double position, double bpm);

    // BonjourDiscovery::Listener implementation
    void deviceDiscovered(const BonjourDiscovery::DiscoveredDevice& device) override;
    void deviceLost(const std::string& deviceName) override;
    void deviceConnected(const BonjourDiscovery::DiscoveredDevice& device) override;
    
    // ThunderboltNetworkDiscovery::Listener implementation
    void peerDiscovered(const ThunderboltNetworkDiscovery::PeerDevice& device) override;
    void peerLost(const std::string& device_name) override;
    void connectionEstablished(const ThunderboltNetworkDiscovery::PeerDevice& device) override;
    
    // WiFiNetworkDiscovery::Listener implementation
    void deviceDiscovered(const WiFiPeer& device) override;
    void discoveryCompleted() override;
    
    // Timer callback
    void timerCallback() override;
    
    // Helper methods
    void updateUI();
    void updatePerformanceDisplay();
    void networkModeChanged();
    juce::Font getEmojiCompatibleFont(float size = 12.0f);
    
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(JAMNetworkPanel)
};
