import React, { useState, useEffect, useCallback } from "react";
import "@/App.css";
import axios from "axios";
import { Toaster, toast } from "sonner";
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Settings,
  Play,
  Square,
  RefreshCw,
  AlertTriangle,
  ShieldCheck,
  ShieldAlert,
  Zap,
  Clock,
  DollarSign,
  Target,
  BarChart2,
  List,
  ChevronRight,
  X
} from "lucide-react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area
} from "recharts";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API = `${BACKEND_URL}/api`;

// ==================== COMPONENTS ====================

// Risk Meter Component
const RiskMeter = ({ label, current, limit, remaining, status, amount }) => {
  const percentage = Math.min((current / limit) * 100, 100);
  const statusColors = {
    SAFE: "risk-meter-safe",
    WARNING: "risk-meter-warning",
    DANGER: "risk-meter-danger"
  };

  return (
    <div className="mb-4" data-testid={`risk-meter-${label.toLowerCase().replace(/\s/g, "-")}`}>
      <div className="flex justify-between items-center mb-2">
        <span className="text-xs text-gray-400 uppercase tracking-wider">{label}</span>
        <span className={`font-mono text-sm ${status === "SAFE" ? "text-green-500" : status === "WARNING" ? "text-yellow-500" : "text-red-500"}`}>
          {current.toFixed(2)}% / {limit}%
        </span>
      </div>
      <div className="risk-meter">
        <div
          className={`risk-meter-fill ${statusColors[status]}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <div className="flex justify-between mt-1">
        <span className="text-xs text-gray-500">Restant: {remaining.toFixed(2)}%</span>
        <span className="text-xs text-gray-500 font-mono">${amount.toLocaleString()}</span>
      </div>
    </div>
  );
};

// Stat Card Component
const StatCard = ({ title, value, subtitle, icon: Icon, trend, className = "" }) => {
  const isPositive = trend === "up" || (typeof value === "number" && value > 0);
  const isNegative = trend === "down" || (typeof value === "number" && value < 0);

  return (
    <div className={`card ${className}`} data-testid={`stat-card-${title.toLowerCase().replace(/\s/g, "-")}`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-gray-400 uppercase tracking-wider mb-1">{title}</p>
          <p className={`stat-value ${isPositive ? "stat-value-profit" : isNegative ? "stat-value-loss" : "text-white"}`}>
            {typeof value === "number" ? value.toLocaleString(undefined, { minimumFractionDigits: 2 }) : value}
          </p>
          {subtitle && <p className="stat-label">{subtitle}</p>}
        </div>
        {Icon && (
          <div className={`p-2 rounded-lg ${isPositive ? "bg-green-500/10" : isNegative ? "bg-red-500/10" : "bg-gray-500/10"}`}>
            <Icon size={20} className={isPositive ? "text-green-500" : isNegative ? "text-red-500" : "text-gray-400"} />
          </div>
        )}
      </div>
    </div>
  );
};

// Trade Row Component
const TradeRow = ({ trade }) => {
  const isProfit = trade.pnl > 0;
  const isBuy = trade.direction === "BUY";

  return (
    <tr data-testid={`trade-row-${trade.id}`}>
      <td>
        <span className={`badge ${isBuy ? "badge-profit" : "badge-loss"}`}>
          {isBuy ? <TrendingUp size={12} className="mr-1" /> : <TrendingDown size={12} className="mr-1" />}
          {trade.direction}
        </span>
      </td>
      <td className="text-white">{trade.symbol}</td>
      <td>{trade.entry_price?.toFixed(5)}</td>
      <td>{trade.exit_price?.toFixed(5) || "-"}</td>
      <td>{trade.lot_size}</td>
      <td>
        <span className={`badge ${trade.strategy === "SCALPING" ? "badge-neutral" : "badge-warning"}`}>
          {trade.strategy}
        </span>
      </td>
      <td>
        <span className={isProfit ? "text-green-500" : "text-red-500"}>
          {isProfit ? "+" : ""}{trade.pnl?.toFixed(2) || "0.00"}
        </span>
      </td>
      <td>
        <span className={`badge ${trade.status === "OPEN" ? "badge-warning" : trade.status === "CLOSED" ? (isProfit ? "badge-profit" : "badge-loss") : "badge-neutral"}`}>
          {trade.status}
        </span>
      </td>
    </tr>
  );
};

// Signal Card Component
const SignalCard = ({ signal, onExecute }) => {
  const isBuy = signal.direction === "BUY";

  return (
    <div className={`signal-card ${isBuy ? "signal-buy" : "signal-sell"}`} data-testid={`signal-${signal.symbol}-${signal.direction}`}>
      <div className="flex justify-between items-start mb-2">
        <div className="flex items-center gap-2">
          {isBuy ? (
            <TrendingUp size={16} className="text-green-500" />
          ) : (
            <TrendingDown size={16} className="text-red-500" />
          )}
          <span className="font-bold text-white">{signal.direction} {signal.symbol}</span>
        </div>
        <span className={`badge ${signal.valid ? "badge-profit" : "badge-loss"}`}>
          {signal.confidence}%
        </span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs font-mono mb-2">
        <div>
          <span className="text-gray-500">Entry</span>
          <p className="text-white">{signal.entry_price?.toFixed(5)}</p>
        </div>
        <div>
          <span className="text-gray-500">SL</span>
          <p className="text-red-400">{signal.stop_loss?.toFixed(5)}</p>
        </div>
        <div>
          <span className="text-gray-500">TP</span>
          <p className="text-green-400">{signal.take_profit?.toFixed(5)}</p>
        </div>
      </div>
      <p className="text-xs text-gray-400 mb-2">{signal.reason}</p>
      <div className="flex justify-between items-center">
        <span className={`text-xs ${signal.strategy === "SCALPING" ? "text-blue-400" : "text-yellow-400"}`}>
          {signal.strategy}
        </span>
        {signal.valid && (
          <button
            onClick={() => onExecute(signal)}
            className="btn btn-primary text-xs py-1 px-2"
            data-testid={`execute-signal-${signal.symbol}`}
          >
            <Zap size={12} />
            Exécuter
          </button>
        )}
      </div>
    </div>
  );
};

// Market Quote Row
const MarketQuote = ({ quote }) => (
  <div className="flex justify-between items-center py-2 border-b border-gray-800" data-testid={`quote-${quote.symbol}`}>
    <span className="text-white font-medium">{quote.symbol}</span>
    <div className="flex gap-4 font-mono text-sm">
      <span className="text-red-400">{quote.bid?.toFixed(5)}</span>
      <span className="text-green-400">{quote.ask?.toFixed(5)}</span>
      <span className="text-gray-500">{quote.spread}</span>
    </div>
  </div>
);

// Settings Modal
const SettingsModal = ({ isOpen, onClose, settings, onSave }) => {
  const [formData, setFormData] = useState(settings || {});

  useEffect(() => {
    setFormData(settings || {});
  }, [settings]);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    onSave(formData);
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-testid="settings-modal">
      <div className="card w-full max-w-md mx-4">
        <div className="card-header">
          <h2 className="card-title flex items-center gap-2">
            <Settings size={18} />
            Paramètres du Bot
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" data-testid="close-settings">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="input-label">Scalping Lot Size</label>
              <input
                type="number"
                step="0.01"
                className="input-field"
                value={formData.scalping_lot_size || 0.1}
                onChange={(e) => setFormData({ ...formData, scalping_lot_size: parseFloat(e.target.value) })}
                data-testid="scalping-lot-input"
              />
            </div>
            <div>
              <label className="input-label">Intraday Lot Size</label>
              <input
                type="number"
                step="0.01"
                className="input-field"
                value={formData.intraday_lot_size || 0.05}
                onChange={(e) => setFormData({ ...formData, intraday_lot_size: parseFloat(e.target.value) })}
                data-testid="intraday-lot-input"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="input-label">Scalping TP (pips)</label>
              <input
                type="number"
                className="input-field"
                value={formData.scalping_tp_pips || 10}
                onChange={(e) => setFormData({ ...formData, scalping_tp_pips: parseInt(e.target.value) })}
                data-testid="scalping-tp-input"
              />
            </div>
            <div>
              <label className="input-label">Scalping SL (pips)</label>
              <input
                type="number"
                className="input-field"
                value={formData.scalping_sl_pips || 10}
                onChange={(e) => setFormData({ ...formData, scalping_sl_pips: parseInt(e.target.value) })}
                data-testid="scalping-sl-input"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="input-label">Intraday TP (pips)</label>
              <input
                type="number"
                className="input-field"
                value={formData.intraday_tp_pips || 30}
                onChange={(e) => setFormData({ ...formData, intraday_tp_pips: parseInt(e.target.value) })}
                data-testid="intraday-tp-input"
              />
            </div>
            <div>
              <label className="input-label">Intraday SL (pips)</label>
              <input
                type="number"
                className="input-field"
                value={formData.intraday_sl_pips || 20}
                onChange={(e) => setFormData({ ...formData, intraday_sl_pips: parseInt(e.target.value) })}
                data-testid="intraday-sl-input"
              />
            </div>
          </div>

          <div className="flex items-center gap-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.scalping_enabled !== false}
                onChange={(e) => setFormData({ ...formData, scalping_enabled: e.target.checked })}
                className="w-4 h-4"
                data-testid="scalping-enabled-checkbox"
              />
              <span className="text-sm text-gray-300">Scalping activé</span>
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={formData.intraday_enabled !== false}
                onChange={(e) => setFormData({ ...formData, intraday_enabled: e.target.checked })}
                className="w-4 h-4"
                data-testid="intraday-enabled-checkbox"
              />
              <span className="text-sm text-gray-300">Intraday activé</span>
            </label>
          </div>

          <div className="flex gap-2 pt-2">
            <button type="button" onClick={onClose} className="btn btn-outline flex-1" data-testid="cancel-settings">
              Annuler
            </button>
            <button type="submit" className="btn btn-primary flex-1" data-testid="save-settings">
              Sauvegarder
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

// ==================== MAIN APP ====================

function App() {
  // State
  const [dashboard, setDashboard] = useState(null);
  const [signals, setSignals] = useState([]);
  const [equityCurve, setEquityCurve] = useState([]);
  const [dailyStats, setDailyStats] = useState([]);
  const [loading, setLoading] = useState(true);
  const [botActive, setBotActive] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [settings, setSettings] = useState(null);
  const [activeTab, setActiveTab] = useState("dashboard");
  const [trades, setTrades] = useState([]);

  // Fetch dashboard data
  const fetchDashboard = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/dashboard`);
      setDashboard(response.data);
      setBotActive(response.data.bot_active);
    } catch (error) {
      console.error("Dashboard fetch error:", error);
    }
  }, []);

  // Fetch signals
  const fetchSignals = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/bot/signals`);
      setSignals(response.data.signals || []);
    } catch (error) {
      console.error("Signals fetch error:", error);
    }
  }, []);

  // Fetch equity curve
  const fetchEquityCurve = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/stats/equity-curve`);
      setEquityCurve(response.data.curve || []);
    } catch (error) {
      console.error("Equity curve fetch error:", error);
    }
  }, []);

  // Fetch daily stats
  const fetchDailyStats = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/stats/daily`);
      setDailyStats(response.data.stats || []);
    } catch (error) {
      console.error("Daily stats fetch error:", error);
    }
  }, []);

  // Fetch settings
  const fetchSettings = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/settings`);
      setSettings(response.data);
    } catch (error) {
      console.error("Settings fetch error:", error);
    }
  }, []);

  // Fetch trades
  const fetchTrades = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/trades?limit=50`);
      setTrades(response.data.trades || []);
    } catch (error) {
      console.error("Trades fetch error:", error);
    }
  }, []);

  // Initial load
  useEffect(() => {
    const loadData = async () => {
      setLoading(true);
      await Promise.all([
        fetchDashboard(),
        fetchSignals(),
        fetchEquityCurve(),
        fetchDailyStats(),
        fetchSettings(),
        fetchTrades()
      ]);
      setLoading(false);
    };
    loadData();
  }, [fetchDashboard, fetchSignals, fetchEquityCurve, fetchDailyStats, fetchSettings, fetchTrades]);

  // Auto-refresh
  useEffect(() => {
    const interval = setInterval(() => {
      fetchDashboard();
      fetchSignals();
    }, 5000);
    return () => clearInterval(interval);
  }, [fetchDashboard, fetchSignals]);

  // Bot control
  const toggleBot = async () => {
    try {
      if (botActive) {
        await axios.post(`${API}/bot/stop`);
        toast.info("Bot arrêté");
      } else {
        await axios.post(`${API}/bot/start`);
        toast.success("Bot démarré");
      }
      setBotActive(!botActive);
    } catch (error) {
      toast.error("Erreur lors du contrôle du bot");
    }
  };

  // Save settings
  const saveSettings = async (newSettings) => {
    try {
      await axios.put(`${API}/settings`, newSettings);
      setSettings(newSettings);
      toast.success("Paramètres sauvegardés");
    } catch (error) {
      toast.error("Erreur lors de la sauvegarde");
    }
  };

  // Execute signal
  const executeSignal = async (signal) => {
    try {
      const lotSize = signal.strategy === "SCALPING"
        ? settings?.scalping_lot_size || 0.1
        : settings?.intraday_lot_size || 0.05;

      await axios.post(`${API}/trades`, {
        symbol: signal.symbol,
        direction: signal.direction,
        entry_price: signal.entry_price,
        stop_loss: signal.stop_loss,
        take_profit: signal.take_profit,
        lot_size: lotSize,
        strategy: signal.strategy
      });

      toast.success(`Trade ouvert: ${signal.direction} ${signal.symbol}`);
      fetchDashboard();
      fetchTrades();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Erreur lors de l'exécution");
    }
  };

  // Generate demo data
  const generateDemoData = async () => {
    try {
      setLoading(true);
      await axios.post(`${API}/demo/generate-trades`);
      toast.success("Données démo générées");
      await Promise.all([
        fetchDashboard(),
        fetchEquityCurve(),
        fetchDailyStats(),
        fetchTrades()
      ]);
    } catch (error) {
      toast.error("Erreur lors de la génération");
    } finally {
      setLoading(false);
    }
  };

  // Refresh all
  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([
      fetchDashboard(),
      fetchSignals(),
      fetchEquityCurve(),
      fetchTrades()
    ]);
    setLoading(false);
    toast.success("Données actualisées");
  };

  if (loading && !dashboard) {
    return (
      <div className="min-h-screen flex items-center justify-center" data-testid="loading-screen">
        <div className="text-center">
          <div className="spinner mx-auto mb-4" />
          <p className="text-gray-400">Chargement du dashboard...</p>
        </div>
      </div>
    );
  }

  const account = dashboard?.account || {};
  const riskStatus = dashboard?.risk_status || {};
  const marketData = dashboard?.market_data || [];
  const indicators = dashboard?.indicators || {};
  const recentTrades = dashboard?.recent_trades || [];
  const openTrades = dashboard?.open_trades || [];

  return (
    <div className="min-h-screen" data-testid="main-app">
      <Toaster position="top-right" theme="dark" />

      {/* Navigation */}
      <nav className="nav-header" data-testid="nav-header">
        <div className="flex items-center gap-4">
          <h1 className="nav-logo">FTMO<span className="text-green-500">DASH</span></h1>
          <div className="bot-status">
            <div className={`bot-status-dot ${botActive ? "bot-status-active" : "bot-status-inactive"}`} />
            <span className="text-sm text-gray-400">{botActive ? "Bot Actif" : "Bot Inactif"}</span>
          </div>
        </div>

        <div className="nav-actions">
          <button onClick={generateDemoData} className="btn btn-outline" data-testid="generate-demo-btn">
            <BarChart2 size={16} />
            Démo
          </button>
          <button onClick={refreshAll} className="btn btn-outline" data-testid="refresh-btn">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
          <button onClick={() => setShowSettings(true)} className="btn btn-outline" data-testid="settings-btn">
            <Settings size={16} />
          </button>
          <button
            onClick={toggleBot}
            className={`btn ${botActive ? "btn-danger" : "btn-primary"}`}
            data-testid="toggle-bot-btn"
          >
            {botActive ? <Square size={16} /> : <Play size={16} />}
            {botActive ? "Arrêter" : "Démarrer"}
          </button>
        </div>
      </nav>

      {/* Tabs */}
      <div className="px-4 pt-4 max-w-[1600px] mx-auto">
        <div className="tab-list">
          <button
            className={`tab-item ${activeTab === "dashboard" ? "tab-item-active" : ""}`}
            onClick={() => setActiveTab("dashboard")}
            data-testid="tab-dashboard"
          >
            <Activity size={14} className="inline mr-2" />
            Dashboard
          </button>
          <button
            className={`tab-item ${activeTab === "trades" ? "tab-item-active" : ""}`}
            onClick={() => setActiveTab("trades")}
            data-testid="tab-trades"
          >
            <List size={14} className="inline mr-2" />
            Trades
          </button>
          <button
            className={`tab-item ${activeTab === "signals" ? "tab-item-active" : ""}`}
            onClick={() => setActiveTab("signals")}
            data-testid="tab-signals"
          >
            <Zap size={14} className="inline mr-2" />
            Signaux
          </button>
        </div>
      </div>

      {/* Dashboard Tab */}
      {activeTab === "dashboard" && (
        <div className="dashboard-grid" data-testid="dashboard-content">
          {/* Risk Management - Hero Section */}
          <div className="card col-span-12 md:col-span-6 lg:col-span-4" data-testid="risk-widget">
            <div className="card-header">
              <h2 className="card-title flex items-center gap-2">
                {riskStatus.can_trade ? (
                  <ShieldCheck size={18} className="text-green-500" />
                ) : (
                  <ShieldAlert size={18} className="text-red-500" />
                )}
                Gestion des Risques FTMO
              </h2>
            </div>

            <RiskMeter
              label="Perte Journalière"
              current={riskStatus.daily_loss_percent || 0}
              limit={riskStatus.daily_loss_limit || 4.5}
              remaining={riskStatus.daily_remaining_percent || 4.5}
              status={riskStatus.daily_status || "SAFE"}
              amount={riskStatus.daily_remaining_amount || 4500}
            />

            <RiskMeter
              label="Drawdown Total"
              current={riskStatus.total_loss_percent || 0}
              limit={riskStatus.total_loss_limit || 10}
              remaining={riskStatus.total_remaining_percent || 10}
              status={riskStatus.total_status || "SAFE"}
              amount={riskStatus.total_remaining_amount || 10000}
            />

            <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t border-gray-800">
              <div className="text-center">
                <p className="text-xs text-gray-500 mb-1">Max Risque/Trade</p>
                <p className="font-mono text-lg text-white">{riskStatus.max_risk_per_trade || 1}%</p>
              </div>
              <div className="text-center">
                <p className="text-xs text-gray-500 mb-1">RR Minimum</p>
                <p className="font-mono text-lg text-white">{riskStatus.min_risk_reward || 1}:1</p>
              </div>
            </div>
          </div>

          {/* Account Stats */}
          <div className="col-span-12 md:col-span-6 lg:col-span-4 grid grid-cols-2 gap-4">
            <StatCard
              title="Solde"
              value={account.current_balance || 100000}
              subtitle="Balance courante"
              icon={DollarSign}
            />
            <StatCard
              title="P&L Jour"
              value={account.daily_pnl || 0}
              subtitle={`${account.daily_pnl_percent || 0}%`}
              icon={account.daily_pnl >= 0 ? TrendingUp : TrendingDown}
              trend={account.daily_pnl >= 0 ? "up" : "down"}
            />
            <StatCard
              title="P&L Total"
              value={account.total_pnl || 0}
              subtitle={`${account.total_pnl_percent || 0}%`}
              icon={account.total_pnl >= 0 ? TrendingUp : TrendingDown}
              trend={account.total_pnl >= 0 ? "up" : "down"}
            />
            <StatCard
              title="Win Rate"
              value={`${account.win_rate || 0}%`}
              subtitle={`${account.winning_trades || 0}W / ${account.losing_trades || 0}L`}
              icon={Target}
            />
          </div>

          {/* Equity Curve */}
          <div className="card col-span-12 md:col-span-6 lg:col-span-4" data-testid="equity-chart">
            <div className="card-header">
              <h2 className="card-title">Courbe d'Équité</h2>
            </div>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={equityCurve}>
                  <defs>
                    <linearGradient id="equityGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#22C55E" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#22C55E" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="index" hide />
                  <YAxis
                    domain={["auto", "auto"]}
                    tick={{ fill: "#71717A", fontSize: 10 }}
                    tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
                  />
                  <Tooltip
                    contentStyle={{
                      background: "#18181B",
                      border: "1px solid #27272A",
                      borderRadius: 8,
                      fontFamily: "JetBrains Mono"
                    }}
                    formatter={(value) => [`$${value.toLocaleString()}`, "Équité"]}
                  />
                  <Area
                    type="monotone"
                    dataKey="equity"
                    stroke="#22C55E"
                    fill="url(#equityGradient)"
                    strokeWidth={2}
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Market Data */}
          <div className="card col-span-12 md:col-span-6 lg:col-span-4" data-testid="market-data">
            <div className="card-header">
              <h2 className="card-title">Marché en Direct</h2>
            </div>
            <div className="text-xs text-gray-500 flex justify-between mb-2 px-1">
              <span>Paire</span>
              <div className="flex gap-4">
                <span className="w-16 text-right">Bid</span>
                <span className="w-16 text-right">Ask</span>
                <span className="w-8 text-right">Sprd</span>
              </div>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {marketData.map((quote) => (
                <MarketQuote key={quote.symbol} quote={quote} />
              ))}
            </div>
          </div>

          {/* Technical Indicators */}
          <div className="card col-span-12 md:col-span-6 lg:col-span-4" data-testid="indicators">
            <div className="card-header">
              <h2 className="card-title">Indicateurs EUR/USD</h2>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">RSI (14)</p>
                <p className={`font-mono text-lg ${indicators.rsi > 70 ? "text-red-400" : indicators.rsi < 30 ? "text-green-400" : "text-white"}`}>
                  {indicators.rsi?.toFixed(1) || "-"}
                </p>
              </div>
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">MACD</p>
                <p className={`font-mono text-lg ${indicators.macd > 0 ? "text-green-400" : "text-red-400"}`}>
                  {indicators.macd?.toFixed(5) || "-"}
                </p>
              </div>
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">EMA 8</p>
                <p className="font-mono text-white">{indicators.ema_8?.toFixed(5) || "-"}</p>
              </div>
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">EMA 21</p>
                <p className="font-mono text-white">{indicators.ema_21?.toFixed(5) || "-"}</p>
              </div>
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">Support</p>
                <p className="font-mono text-green-400">{indicators.support?.toFixed(5) || "-"}</p>
              </div>
              <div className="bg-gray-900/50 rounded p-2">
                <p className="text-xs text-gray-500">Résistance</p>
                <p className="font-mono text-red-400">{indicators.resistance?.toFixed(5) || "-"}</p>
              </div>
            </div>
          </div>

          {/* Active Signals */}
          <div className="card col-span-12 md:col-span-6 lg:col-span-4" data-testid="signals-widget">
            <div className="card-header">
              <h2 className="card-title flex items-center gap-2">
                <Zap size={16} className="text-yellow-500" />
                Signaux Actifs
              </h2>
              <span className="badge badge-neutral">{signals.length}</span>
            </div>
            <div className="max-h-64 overflow-y-auto">
              {signals.length === 0 ? (
                <p className="text-gray-500 text-sm text-center py-8">Aucun signal actif</p>
              ) : (
                signals.map((signal, idx) => (
                  <SignalCard key={idx} signal={signal} onExecute={executeSignal} />
                ))
              )}
            </div>
          </div>

          {/* Recent Trades */}
          <div className="card col-span-12" data-testid="recent-trades">
            <div className="card-header">
              <h2 className="card-title flex items-center gap-2">
                <Clock size={16} />
                Trades Récents
              </h2>
              <button
                className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
                onClick={() => setActiveTab("trades")}
                data-testid="view-all-trades"
              >
                Voir tout <ChevronRight size={14} />
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="trade-table">
                <thead>
                  <tr>
                    <th>Direction</th>
                    <th>Symbole</th>
                    <th>Entrée</th>
                    <th>Sortie</th>
                    <th>Lots</th>
                    <th>Stratégie</th>
                    <th>P&L</th>
                    <th>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {recentTrades.slice(0, 5).map((trade) => (
                    <TradeRow key={trade.id} trade={trade} />
                  ))}
                  {recentTrades.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center text-gray-500 py-8">
                        Aucun trade. Cliquez sur "Démo" pour générer des données.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Trades Tab */}
      {activeTab === "trades" && (
        <div className="px-4 pb-4 max-w-[1600px] mx-auto" data-testid="trades-content">
          <div className="card">
            <div className="card-header">
              <h2 className="card-title">Historique des Trades</h2>
              <span className="badge badge-neutral">{trades.length} trades</span>
            </div>
            <div className="overflow-x-auto">
              <table className="trade-table">
                <thead>
                  <tr>
                    <th>Direction</th>
                    <th>Symbole</th>
                    <th>Entrée</th>
                    <th>Sortie</th>
                    <th>Lots</th>
                    <th>Stratégie</th>
                    <th>P&L</th>
                    <th>Statut</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.map((trade) => (
                    <TradeRow key={trade.id} trade={trade} />
                  ))}
                  {trades.length === 0 && (
                    <tr>
                      <td colSpan={8} className="text-center text-gray-500 py-8">
                        Aucun trade enregistré
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Signals Tab */}
      {activeTab === "signals" && (
        <div className="px-4 pb-4 max-w-[1600px] mx-auto" data-testid="signals-content">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {signals.length === 0 ? (
              <div className="card col-span-full">
                <div className="text-center py-12">
                  <Zap size={48} className="mx-auto mb-4 text-gray-600" />
                  <h3 className="text-lg text-gray-400 mb-2">Aucun signal détecté</h3>
                  <p className="text-sm text-gray-500">
                    Les stratégies analysent le marché en permanence.
                    <br />
                    Les signaux apparaîtront quand les conditions seront réunies.
                  </p>
                </div>
              </div>
            ) : (
              signals.map((signal, idx) => (
                <div key={idx} className="card">
                  <SignalCard signal={signal} onExecute={executeSignal} />
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Settings Modal */}
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        settings={settings}
        onSave={saveSettings}
      />
    </div>
  );
}

export default App;
