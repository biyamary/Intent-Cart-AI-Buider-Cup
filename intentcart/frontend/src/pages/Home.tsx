import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ArrowUpRight,
  Armchair,
  Check,
  MessageCircle,
  ScanLine,
  Shirt,
  Sparkles,
  Watch,
} from 'lucide-react'
import { agentList, agents } from '../lib/agents'

const agentIcons = {
  food: ScanLine,
  stylist: Shirt,
} as const

export function Home() {
  return (
    <div className="home">
      <section className="hero" aria-labelledby="home-heading">
        <div className="hero-copy">
          <div className="eyebrow">
            <span className="dot" /> TWO SPECIALISTS. ONE EASIER CART.
          </div>
          <h1 id="home-heading">
            Ask. Decide.
            <br /> Shop with <em>confidence.</em>
          </h1>
          <p>
            Start a conversation with the specialist you need. Nia makes food labels clearer. Mira
            builds a complete look around you and your budget.
          </p>
          <div className="hero-actions" aria-label="Choose a specialist">
            {agentList.map((agent) => {
              const Icon = agentIcons[agent.id]
              return (
                <Link
                  className={`button hero-agent-button hero-agent-${agent.id}`}
                  to={agent.route}
                  key={agent.id}
                  aria-label={`Chat with ${agent.name}, ${agent.role}`}
                >
                  <Icon size={18} aria-hidden="true" />
                  <span>
                    Chat with {agent.name}
                    <small>{agent.role}</small>
                  </span>
                  <ArrowUpRight size={17} aria-hidden="true" />
                </Link>
              )
            })}
          </div>
          <span className="hero-assurance">
            <MessageCircle size={14} aria-hidden="true" /> Just describe what you need — they’ll
            guide the next step.
          </span>
        </div>
        <div
          className="hero-art"
          role="img"
          aria-label="Meet Nia and Mira, your shopping specialists"
        >
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="art-card art-food" aria-hidden="true">
            <div className="art-agent-heading">
              <span className="agent-avatar">N</span>
              <span>
                <strong>{agents.food.name}</strong>
                <small>{agents.food.role}</small>
              </span>
            </div>
            <p>“Let’s take a closer look at that label.”</p>
            <div className="fake-lines">
              <i />
              <i />
              <i />
            </div>
            <div className="art-chip">
              <Check size={13} /> Your preferences, considered
            </div>
          </div>
          <div className="art-card art-look" aria-hidden="true">
            <div className="art-agent-heading">
              <span className="agent-avatar">M</span>
              <span>
                <strong>{agents.stylist.name}</strong>
                <small>{agents.stylist.role}</small>
              </span>
            </div>
            <Shirt size={46} strokeWidth={1} />
            <p>“I’ll bring the whole look together.”</p>
            <div className="palette">
              <i />
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="art-sticker">
            Help that feels
            <br />
            <em>personal.</em>
          </div>
        </div>
      </section>
      <section className="home-section" aria-labelledby="specialists-heading">
        <div className="section-heading">
          <div>
            <span className="eyebrow">WHO CAN HELP TODAY?</span>
            <h2 id="specialists-heading">Meet your shopping specialists.</h2>
          </div>
          <span className="muted">Choose one and start with a simple message</span>
        </div>
        <div className="flow-grid">
          {agentList.map((agent, index) => {
            const Icon = agentIcons[agent.id]
            return (
              <article
                className={`flow-card ${agent.id === 'food' ? 'food-card' : 'clothes-card'}`}
                key={agent.id}
              >
                <div className="flow-icon" aria-hidden="true">
                  <Icon size={26} />
                </div>
                <span className="eyebrow">
                  0{index + 1} / {agent.shortRole.toUpperCase()}
                </span>
                <div className="agent-title-row">
                  <h2>{agent.name}</h2>
                  <span>{agent.role}</span>
                </div>
                <p>{agent.description}</p>
                <ul className="agent-capabilities" aria-label={`${agent.name} can help you`}>
                  {agent.capabilities.map((capability) => (
                    <li key={capability}>
                      <Check size={13} aria-hidden="true" /> {capability}
                    </li>
                  ))}
                </ul>
                <div className="example-prompt">
                  <Sparkles size={15} aria-hidden="true" />
                  <span>
                    <small>TRY ASKING</small>“{agent.examplePrompt}”
                  </span>
                </div>
                <Link
                  className="flow-link"
                  to={agent.route}
                  aria-label={`Chat with ${agent.name}, ${agent.role}`}
                >
                  <span>
                    Chat with {agent.name}
                    <small>Open a new conversation</small>
                  </span>
                  <ArrowRight size={20} aria-hidden="true" />
                </Link>
              </article>
            )
          })}
        </div>
      </section>
      <section className="coming-row">
        <span>More everyday choices, on the horizon.</span>
        <span>
          <Armchair size={17} /> Furniture <small>Coming soon</small>
        </span>
        <span>
          <Watch size={17} /> Accessories <small>Coming soon</small>
        </span>
      </section>
    </div>
  )
}
