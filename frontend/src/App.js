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

// Backtesting Modal
const BacktestModal = ({ isOpen, onClose }) => {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);
  const [config, setConfig] = useState({
    symbol: "EURUSD",
    strategy: "BOTH",
    days: 180,
    timeframe: "H1",
    initial_balance: 100000
  });

  if (!isOpen) return null;

  const runBacktest = async () => {
    setRunning(true);
    setResult(null);
    
    try {
      const response = await axios.post(`${API}/backtest/run`, config);
      if (response.data.success) {
        setResult(response.data.result);
        toast.success("Backtest terminé!");
      } else {
        toast.error(response.data.error);
      }
    } catch (error) {
      toast.error("Erreur lors du backtest");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50 overflow-y-auto" data-testid="backtest-modal">
      <div className="card w-full max-w-4xl mx-4 my-8 max-h-[90vh] overflow-y-auto">
        <div className="card-header sticky top-0 bg-[#18181B] z-10">
          <h2 className="card-title flex items-center gap-2">
            <BarChart2 size={18} className="text-blue-500" />
            Backtesting des Stratégies
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" data-testid="close-backtest">
            <X size={20} />
          </button>
        </div>

        {/* Configuration */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div>
            <label className="input-label">Symbole</label>
            <select
              className="input-field"
              value={config.symbol}
              onChange={(e) => setConfig({...config, symbol: e.target.value})}
              data-testid="backtest-symbol"
            >
              <option value="EURUSD">EUR/USD</option>
            </select>
          </div>
          <div>
            <label className="input-label">Stratégie</label>
            <select
              className="input-field"
              value={config.strategy}
              onChange={(e) => setConfig({...config, strategy: e.target.value})}
              data-testid="backtest-strategy"
            >
              <option value="BOTH">Les deux</option>
              <option value="SCALPING">Scalping</option>
              <option value="INTRADAY">Intraday</option>
            </select>
          </div>
          <div>
            <label className="input-label">Période (jours)</label>
            <select
              className="input-field"
              value={config.days}
              onChange={(e) => setConfig({...config, days: parseInt(e.target.value)})}
              data-testid="backtest-days"
            >
              <option value={30}>30 jours</option>
              <option value={90}>90 jours</option>
              <option value={180}>180 jours (6 mois)</option>
              <option value={365}>365 jours (1 an)</option>
            </select>
          </div>
          <div>
            <label className="input-label">Timeframe</label>
            <select
              className="input-field"
              value={config.timeframe}
              onChange={(e) => setConfig({...config, timeframe: e.target.value})}
              data-testid="backtest-timeframe"
            >
              <option value="M15">15 minutes</option>
              <option value="H1">1 heure</option>
              <option value="H4">4 heures</option>
            </select>
          </div>
        </div>

        <button
          onClick={runBacktest}
          disabled={running}
          className="btn btn-primary w-full mb-6"
          data-testid="run-backtest-btn"
        >
          {running ? (
            <>
              <div className="spinner" style={{width: 16, height: 16}} />
              Backtest en cours... (peut prendre 30-60 secondes)
            </>
          ) : (
            <>
              <Play size={16} />
              Lancer le Backtest
            </>
          )}
        </button>

        {/* Results */}
        {result && (
          <div className="space-y-6">
            {/* Summary Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className={`card ${result.total_return >= 0 ? "border-green-500/30" : "border-red-500/30"}`}>
                <p className="text-xs text-gray-400 mb-1">Rendement Total</p>
                <p className={`stat-value text-xl ${result.total_return >= 0 ? "text-green-500" : "text-red-500"}`}>
                  {result.total_return >= 0 ? "+" : ""}{result.total_return_percent}%
                </p>
                <p className="text-xs text-gray-500 font-mono">
                  ${result.total_return.toLocaleString()}
                </p>
              </div>
              
              <div className="card">
                <p className="text-xs text-gray-400 mb-1">Win Rate</p>
                <p className="stat-value text-xl text-white">{result.win_rate}%</p>
                <p className="text-xs text-gray-500">
                  {result.winning_trades}W / {result.losing_trades}L
                </p>
              </div>
              
              <div className="card">
                <p className="text-xs text-gray-400 mb-1">Profit Factor</p>
                <p className={`stat-value text-xl ${result.profit_factor >= 1.5 ? "text-green-500" : result.profit_factor >= 1 ? "text-yellow-500" : "text-red-500"}`}>
                  {result.profit_factor}
                </p>
                <p className="text-xs text-gray-500">{result.total_trades} trades</p>
              </div>
              
              <div className={`card ${result.max_drawdown_percent <= 10 ? "border-green-500/30" : "border-red-500/30"}`}>
                <p className="text-xs text-gray-400 mb-1">Max Drawdown</p>
                <p className={`stat-value text-xl ${result.max_drawdown_percent <= 10 ? "text-yellow-500" : "text-red-500"}`}>
                  {result.max_drawdown_percent}%
                </p>
                <p className="text-xs text-gray-500 font-mono">
                  ${result.max_drawdown.toLocaleString()}
                </p>
              </div>
            </div>

            {/* FTMO Compliance */}
            <div className={`card ${!result.ftmo_daily_limit_breached && !result.ftmo_total_limit_breached ? "border-green-500/30" : "border-red-500/30"}`}>
              <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
                {!result.ftmo_daily_limit_breached && !result.ftmo_total_limit_breached ? (
                  <ShieldCheck size={16} className="text-green-500" />
                ) : (
                  <ShieldAlert size={16} className="text-red-500" />
                )}
                Conformité FTMO
              </h3>
              <div className="grid grid-cols-2 gap-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-400">Limite journalière (4.5%)</span>
                  <span className={`badge ${result.ftmo_daily_limit_breached ? "badge-loss" : "badge-profit"}`}>
                    {result.ftmo_daily_limit_breached ? "DÉPASSÉE" : "OK"} ({result.max_daily_loss_percent}%)
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-gray-400">Drawdown total (10%)</span>
                  <span className={`badge ${result.ftmo_total_limit_breached ? "badge-loss" : "badge-profit"}`}>
                    {result.ftmo_total_limit_breached ? "DÉPASSÉ" : "OK"} ({result.max_drawdown_percent}%)
                  </span>
                </div>
              </div>
            </div>

            {/* Detailed Stats */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Gain Moyen</p>
                <p className="font-mono text-green-500">${result.average_win}</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Perte Moyenne</p>
                <p className="font-mono text-red-500">${result.average_loss}</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Risk/Reward Moyen</p>
                <p className="font-mono text-white">{result.avg_risk_reward}:1</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Meilleur Trade</p>
                <p className="font-mono text-green-500">${result.largest_win}</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Pire Trade</p>
                <p className="font-mono text-red-500">${result.largest_loss}</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Durée Moy. Trade</p>
                <p className="font-mono text-white">{result.avg_trade_duration_hours}h</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Sharpe Ratio</p>
                <p className="font-mono text-white">{result.sharpe_ratio}</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Meilleure Heure</p>
                <p className="font-mono text-green-400">{result.best_trading_hour}:00 UTC</p>
              </div>
              <div className="bg-gray-900/50 rounded-lg p-3">
                <p className="text-xs text-gray-500">Pire Heure</p>
                <p className="font-mono text-red-400">{result.worst_trading_hour}:00 UTC</p>
              </div>
            </div>

            {/* Equity Curve */}
            {result.equity_curve && result.equity_curve.length > 0 && (
              <div className="card">
                <h3 className="text-sm font-semibold mb-3">Courbe d'Équité</h3>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={result.equity_curve}>
                      <defs>
                        <linearGradient id="backtestGradient" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="5%" stopColor={result.total_return >= 0 ? "#22C55E" : "#EF4444"} stopOpacity={0.3} />
                          <stop offset="95%" stopColor={result.total_return >= 0 ? "#22C55E" : "#EF4444"} stopOpacity={0} />
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
                        stroke={result.total_return >= 0 ? "#22C55E" : "#EF4444"}
                        fill="url(#backtestGradient)"
                        strokeWidth={2}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* Recent Trades */}
            {result.trades && result.trades.length > 0 && (
              <div className="card">
                <h3 className="text-sm font-semibold mb-3">Derniers Trades ({result.trades.length})</h3>
                <div className="max-h-64 overflow-y-auto">
                  <table className="trade-table text-xs">
                    <thead>
                      <tr>
                        <th>Dir.</th>
                        <th>Stratégie</th>
                        <th>Entrée</th>
                        <th>Sortie</th>
                        <th>P&L</th>
                        <th>Raison</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.trades.slice(-20).map((trade, idx) => (
                        <tr key={idx}>
                          <td>
                            <span className={`badge ${trade.direction === "BUY" ? "badge-profit" : "badge-loss"}`}>
                              {trade.direction}
                            </span>
                          </td>
                          <td>{trade.strategy}</td>
                          <td>{trade.entry_price?.toFixed(5)}</td>
                          <td>{trade.exit_price?.toFixed(5)}</td>
                          <td className={trade.pnl >= 0 ? "text-green-500" : "text-red-500"}>
                            {trade.pnl >= 0 ? "+" : ""}{trade.pnl}
                          </td>
                          <td>
                            <span className={`badge ${trade.exit_reason === "TP" ? "badge-profit" : trade.exit_reason === "SL" ? "badge-loss" : "badge-neutral"}`}>
                              {trade.exit_reason}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

// Connection Modal
const ConnectionModal = ({ isOpen, onClose, onConnect }) => {
  const [connectionType, setConnectionType] = useState("fix");
  const [fixPassword, setFixPassword] = useState("");
  const [openApiData, setOpenApiData] = useState({
    client_id: "",
    client_secret: "",
    access_token: "",
    account_id: "",
    is_live: false
  });
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleFIXConnect = async () => {
    if (!fixPassword) {
      setError("Mot de passe requis");
      return;
    }
    setConnecting(true);
    setError(null);
    
    try {
      const response = await axios.post(`${API}/connection/fix/connect`, {
        password: fixPassword
      });
      
      if (response.data.success) {
        toast.success("Connecté à cTrader FIX!");
        onConnect();
        onClose();
      } else {
        setError(response.data.message);
      }
    } catch (err) {
      setError(err.response?.data?.message || "Erreur de connexion");
    } finally {
      setConnecting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/70 flex items-center justify-center z-50" data-testid="connection-modal">
      <div className="card w-full max-w-lg mx-4">
        <div className="card-header">
          <h2 className="card-title flex items-center gap-2">
            <Activity size={18} className="text-blue-500" />
            Connexion cTrader
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white" data-testid="close-connection">
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="tab-list mb-4">
          <button
            className={`tab-item ${connectionType === "fix" ? "tab-item-active" : ""}`}
            onClick={() => setConnectionType("fix")}
          >
            FIX Protocol
          </button>
          <button
            className={`tab-item ${connectionType === "openapi" ? "tab-item-active" : ""}`}
            onClick={() => setConnectionType("openapi")}
          >
            Open API
          </button>
        </div>

        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3 mb-4 text-red-400 text-sm">
            {error}
          </div>
        )}

        {connectionType === "fix" && (
          <div className="space-y-4">
            <div className="bg-gray-900/50 rounded-lg p-3 text-sm">
              <p className="text-gray-400 mb-2">Configuration FIX détectée :</p>
              <div className="font-mono text-xs space-y-1">
                <p>Host: <span className="text-green-400">live-uk-eqx-01.p.c-trader.com</span></p>
                <p>Port: <span className="text-green-400">5211</span></p>
                <p>Account: <span className="text-green-400">17061677</span></p>
              </div>
            </div>
            
            <div>
              <label className="input-label">Mot de passe FIX API</label>
              <input
                type="password"
                className="input-field"
                value={fixPassword}
                onChange={(e) => setFixPassword(e.target.value)}
                placeholder="Entrez votre mot de passe FIX"
                data-testid="fix-password-input"
              />
              <p className="text-xs text-gray-500 mt-1">
                Obtenu via le dashboard FTMO ou le support
              </p>
            </div>

            <button
              onClick={handleFIXConnect}
              disabled={connecting}
              className="btn btn-primary w-full"
              data-testid="fix-connect-btn"
            >
              {connecting ? (
                <>
                  <div className="spinner" style={{width: 16, height: 16}} />
                  Connexion...
                </>
              ) : (
                <>
                  <Zap size={16} />
                  Connecter FIX
                </>
              )}
            </button>
          </div>
        )}

        {connectionType === "openapi" && (
          <div className="space-y-4">
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 text-sm text-blue-300">
              <p className="font-semibold mb-2">Guide de configuration :</p>
              <ol className="list-decimal list-inside space-y-1 text-xs">
                <li>Allez sur openapi.ctrader.com</li>
                <li>Créez une application</li>
                <li>Notez Client ID et Secret</li>
                <li>Autorisez via l'URL OAuth</li>
              </ol>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="input-label">Client ID</label>
                <input
                  type="text"
                  className="input-field"
                  value={openApiData.client_id}
                  onChange={(e) => setOpenApiData({...openApiData, client_id: e.target.value})}
                />
              </div>
              <div>
                <label className="input-label">Client Secret</label>
                <input
                  type="password"
                  className="input-field"
                  value={openApiData.client_secret}
                  onChange={(e) => setOpenApiData({...openApiData, client_secret: e.target.value})}
                />
              </div>
            </div>

            <div>
              <label className="input-label">Access Token</label>
              <input
                type="text"
                className="input-field"
                value={openApiData.access_token}
                onChange={(e) => setOpenApiData({...openApiData, access_token: e.target.value})}
              />
            </div>

            <div>
              <label className="input-label">Account ID</label>
              <input
                type="number"
                className="input-field"
                value={openApiData.account_id}
                onChange={(e) => setOpenApiData({...openApiData, account_id: e.target.value})}
              />
            </div>

            <button
              className="btn btn-primary w-full opacity-50 cursor-not-allowed"
              disabled
            >
              Configuration requise
            </button>
          </div>
        )}

        <div className="mt-4 pt-4 border-t border-gray-800">
          <p className="text-xs text-gray-500 text-center">
            Mode actuel : <span className="text-yellow-400">Paper Trading (Simulation)</span>
            <br />
            Les vraies données de marché sont utilisées, mais les trades sont simulés.
          </p>
        </div>
      </div>
    </div>
  );
};

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
  const [showConnection, setShowConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState("disconnected");

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

  // Fetch connection status
  const fetchConnectionStatus = useCallback(async () => {
    try {
      const response = await axios.get(`${API}/connection/status`);
      setConnectionStatus(response.data.status);
    } catch (error) {
      console.error("Connection status error:", error);
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
        fetchTrades(),
        fetchConnectionStatus()
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
          <button onClick={() => setShowConnection(true)} className="btn btn-outline" data-testid="connection-btn">
            <Activity size={16} className={connectionStatus === "connected" ? "text-green-500" : ""} />
            {connectionStatus === "connected" ? "Connecté" : "Connexion"}
          </button>
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

      {/* Connection Modal */}
      <ConnectionModal
        isOpen={showConnection}
        onClose={() => setShowConnection(false)}
        onConnect={() => {
          fetchConnectionStatus();
          fetchDashboard();
        }}
      />
    </div>
  );
}

export default App;
