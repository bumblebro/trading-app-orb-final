'use client';

import { CheckCircle2, Circle, Clock, Loader2 } from 'lucide-react';
import type { Signal } from '@/lib/types';

interface StrategyFlowProps {
  phase: string;
  strategyInfo: Signal | null;
}

export default function StrategyFlow({ phase, strategyInfo }: StrategyFlowProps) {
  const steps = [
    {
      id: 'ORB',
      label: 'ORB Building',
      phases: ['BUILDING_ORB'],
      completedPhases: ['WAITING_BREAKOUT', 'BREAKOUT_DETECTED', 'WAITING_PULLBACK', 'IN_ENTRY_ZONE', 'MACD_CONFIRMING', 'ORDER_PLACED', 'IN_TRADE'],
      details: strategyInfo?.orb_range ? `Range: ${strategyInfo.orb_range.toFixed(2)} pts` : '9:15 - 9:30 AM',
    },
    {
      id: 'BREAKOUT',
      label: 'Breakout Detection',
      phases: ['WAITING_BREAKOUT'],
      completedPhases: ['BREAKOUT_DETECTED', 'WAITING_PULLBACK', 'IN_ENTRY_ZONE', 'MACD_CONFIRMING', 'ORDER_PLACED', 'IN_TRADE'],
      details: strategyInfo?.breakout_price ? `Broke ${strategyInfo.breakout_direction === 'UP' ? 'High' : 'Low'} @ ${strategyInfo.breakout_price}` : 'Watching levels...',
    },
    {
      id: 'ENTRY',
      label: 'Order Execution',
      phases: ['ORDER_PLACED', 'IN_TRADE'],
      completedPhases: [],
      details: phase.startsWith('ACTIVE') ? 'Trade Active' : 'Waiting for signal',
    },
  ];

  const getStepStatus = (step: typeof steps[0]) => {
    if (step.completedPhases.includes(phase)) return 'completed';
    if (step.phases.includes(phase)) return 'active';
    if (phase === 'SKIP_TODAY' || phase === 'DISCONNECTED') return 'disabled';
    return 'pending';
  };

  return (
    <div className="strategy-flow-container">
      <div className="flex justify-between items-center mb-6">
        <h3 className="text-sm font-bold uppercase tracking-wider text-gray-400">Strategy Pipeline</h3>
        <div className="flex items-center gap-2">
           <span className={`h-2 w-2 rounded-full ${phase === 'IN_TRADE' ? 'bg-green-500 animate-pulse' : 'bg-gray-600'}`}></span>
           <span className="text-[10px] font-mono text-gray-500">{phase}</span>
        </div>
      </div>

      <div className="flex flex-col gap-4">
        {steps.map((step, idx) => {
          const status = getStepStatus(step);
          const isLast = idx === steps.length - 1;

          return (
            <div key={step.id} className="relative flex items-start gap-4">
              {!isLast && (
                <div className={`absolute left-[11px] top-7 w-[2px] h-8 ${status === 'completed' ? 'bg-green-500' : 'bg-gray-800'}`}></div>
              )}
              
              <div className="z-10 bg-[#0a0a0f] rounded-full">
                {status === 'completed' ? (
                  <CheckCircle2 size={24} className="text-green-500" />
                ) : status === 'active' ? (
                  <div className="relative">
                    <Circle size={24} className="text-blue-500 animate-pulse" />
                    <Loader2 size={12} className="absolute top-1.5 left-1.5 text-blue-500 animate-spin" />
                  </div>
                ) : (
                  <Circle size={24} className="text-gray-800" />
                )}
              </div>

              <div className="flex flex-col">
                <span className={`text-sm font-bold ${status === 'active' ? 'text-blue-400' : status === 'completed' ? 'text-gray-200' : 'text-gray-600'}`}>
                  {step.label}
                </span>
                <span className="text-[11px] text-gray-500 font-mono">
                  {step.details}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <style jsx>{`
        .strategy-flow-container {
          background: var(--bg-card);
          border: 1px solid var(--border);
          border-radius: 16px;
          padding: 1.5rem;
          height: 100%;
        }
      `}</style>
    </div>
  );
}
