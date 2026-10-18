import { Link } from 'react-router-dom'
import { ArrowUpRight, ScanLine, Shirt, Armchair, Watch, Check } from 'lucide-react'

export function Home() {
  return (
    <div className="home">
      <section className="hero">
        <div className="hero-copy">
          <div className="eyebrow">
            <span className="dot" /> A LITTLE CLARITY. A BETTER CHOICE.
          </div>
          <h1>
            Good choices
            <br />
            start with <em>you.</em>
          </h1>
          <p>
            Read between the ingredients. Bring a whole look together. Meet your personal shopping
            companion.
          </p>
          <Link className="button" to="/food">
            Explore food labels <ArrowUpRight size={18} />
          </Link>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="orbit orbit-one" />
          <div className="orbit orbit-two" />
          <div className="art-card art-food">
            <ScanLine size={30} />
            <span>A closer look</span>
            <strong>Know your label.</strong>
            <div className="fake-lines">
              <i />
              <i />
              <i />
            </div>
            <div className="art-chip">
              <Check size={13} /> Your preferences, considered
            </div>
          </div>
          <div className="art-card art-look">
            <Shirt size={57} strokeWidth={1} />
            <strong>It all comes together.</strong>
            <div className="palette">
              <i />
              <i />
              <i />
              <i />
            </div>
          </div>
          <div className="art-sticker">
            A little more
            <br />
            <em>intent.</em>
          </div>
        </div>
      </section>
      <section className="home-section">
        <div className="section-heading">
          <div>
            <span className="eyebrow">WHAT'S ON YOUR MIND?</span>
            <h2>One companion. Two ways to shop.</h2>
          </div>
          <span className="muted">Made for your everyday decisions</span>
        </div>
        <div className="flow-grid">
          <Link className="flow-card food-card" to="/food">
            <div className="flow-icon">
              <ScanLine size={26} />
            </div>
            <span className="eyebrow">01 / FOOD</span>
            <h2>
              What's in it
              <br />
              for you?
            </h2>
            <p>
              Chat with your food companion to decode chemical additives, spot good vs bad ingredients,
              and compare country regulations.
            </p>
            <span className="flow-link">
              Explore food ingredients <ArrowUpRight size={20} />
            </span>
          </Link>
          <Link className="flow-card clothes-card" to="/clothes">
            <div className="flow-icon">
              <Shirt size={26} />
            </div>
            <span className="eyebrow">02 / CLOTHES</span>
            <h2>
              Your occasion.
              <br />
              Your kind of look.
            </h2>
            <p>Tell your stylist about the occasion. Explore ideas and find options together.</p>
            <span className="flow-link">
              Shop a look <ArrowUpRight size={20} />
            </span>
          </Link>
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
