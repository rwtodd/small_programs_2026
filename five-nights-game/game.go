package main

import (
	"math/rand"
)

// --- Constants ---
const (
	NumPiles       = 4
	NumRounds      = 12
	InitialPower   = 100
	PowerDrainCost = 5
	MaxReactions   = 2
)

var (
	Times = []string{
		"12:00 AM", "12:30 AM", "1:00 AM", "1:30 AM", "2:00 AM", "2:30 AM",
		"3:00 AM", "3:30 AM", "4:00 AM", "4:30 AM", "5:00 AM", "5:30 AM",
	}
	PowerDieFaces = []int{0, 0, 5, 5, 10, 10} // 0 = blank
)

// CardType represents a card in the game.
type CardType string

const (
	CardAnimatronic     CardType = "Animatronic"
	CardEmptyRoom       CardType = "Empty Room"
	CardPowerDrain      CardType = "Power Drain"
	CardWhatDown        CardType = "What Was That? Down Arrow"
	CardWhatRight       CardType = "What Was That? Right Arrow"
	CardWhatDoubleRight CardType = "What Was That? Double Right Arrow"
)

func (c CardType) String() string { return string(c) }

// DisplayName returns (prefix, suffix) for two-line display of "What Was That?" cards.
func (c CardType) DisplayName() (string, string) {
	s := string(c)
	if len(s) >= 14 && s[:14] == "What Was That?" {
		rest := s[14:]
		for len(rest) > 0 && rest[0] == ' ' {
			rest = rest[1:]
		}
		return "What Was That?", rest
	}
	return s, ""
}

var initialCounts = map[CardType]int{
	CardAnimatronic:     4,
	CardEmptyRoom:       11,
	CardPowerDrain:      7,
	CardWhatDown:        7,
	CardWhatRight:       12,
	CardWhatDoubleRight: 7,
}

var reactableCards = map[CardType]bool{
	CardAnimatronic:     true,
	CardWhatDown:        true,
	CardWhatRight:       true,
	CardWhatDoubleRight: true,
}

// ResolutionEvent is used to communicate resolution occurrences to the UI.
type ResolutionEventKind int

const (
	EvRevealCard         ResolutionEventKind = iota
	EvDrawReplacement
	EvPileEmpty
	EvLoseGame
	EvAnimatronicMoved
	EvAnimatronicReshuffled
)

type ResolutionEvent struct {
	Kind ResolutionEventKind
	Data interface{}
}

// DrawnCard pairs a card with its pile index.
type DrawnCard struct {
	Card    CardType
	PileIdx int
}

// GameState holds the game state.
type GameState struct {
	Piles        [][]CardType
	Power        int
	CurrentRound int
	GameOver     bool
	Win          bool
}

// NewGameState initializes and sets up a new game.
func NewGameState() *GameState {
	g := &GameState{
		Piles:        make([][]CardType, NumPiles),
		Power:        InitialPower,
		CurrentRound: -1,
	}
	g.setupGame()
	return g
}

func (g *GameState) setupGame() {
	var nonAnimatronic []CardType
	for card, count := range initialCounts {
		if card != CardAnimatronic {
			for i := 0; i < count; i++ {
				nonAnimatronic = append(nonAnimatronic, card)
			}
		}
	}
	rand.Shuffle(len(nonAnimatronic), func(i, j int) {
		nonAnimatronic[i], nonAnimatronic[j] = nonAnimatronic[j], nonAnimatronic[i]
	})

	pileSizes := []int{10, 11, 11, 12}
	start := 0
	for i := 0; i < NumPiles; i++ {
		end := start + pileSizes[i]
		g.Piles[i] = append([]CardType(nil), nonAnimatronic[start:end]...)
		start = end
	}

	animatronics := []CardType{CardAnimatronic, CardAnimatronic, CardAnimatronic, CardAnimatronic}
	g.Piles[0] = append(g.Piles[0], animatronics[0], animatronics[1])
	g.Piles[1] = append(g.Piles[1], animatronics[2])
	g.Piles[2] = append(g.Piles[2], animatronics[3])

	rand.Shuffle(len(g.Piles[0]), func(i, j int) { g.Piles[0][i], g.Piles[0][j] = g.Piles[0][j], g.Piles[0][i] })
	rand.Shuffle(len(g.Piles[1]), func(i, j int) { g.Piles[1][i], g.Piles[1][j] = g.Piles[1][j], g.Piles[1][i] })
	rand.Shuffle(len(g.Piles[2]), func(i, j int) { g.Piles[2][i], g.Piles[2][j] = g.Piles[2][j], g.Piles[2][i] })
}

func (g *GameState) GetPileSizes() []int {
	out := make([]int, NumPiles)
	for i, p := range g.Piles {
		out[i] = len(p)
	}
	return out
}

func (g *GameState) GetPower() int { return g.Power }

func (g *GameState) GetCurrentTime() string {
	if g.CurrentRound >= 0 && g.CurrentRound < len(Times) {
		return Times[g.CurrentRound]
	}
	if g.CurrentRound >= len(Times) {
		return "End of Game"
	}
	return "Before Game Start"
}

func (g *GameState) IsGameOver() bool { return g.GameOver }
func (g *GameState) DidWin() bool     { return g.Win }

func (g *GameState) AdvanceRound() {
	g.CurrentRound++
	if g.CurrentRound >= NumRounds {
		if !g.GameOver {
			g.Win = true
			g.GameOver = true
		}
	}
}

// ConsolidatePiles moves cards from lower piles into empty higher-numbered slots. Returns true if anything changed.
func (g *GameState) ConsolidatePiles() bool {
	var nonEmpty [][]CardType
	for _, p := range g.Piles {
		if len(p) > 0 {
			nonEmpty = append(nonEmpty, p)
		}
	}
	if len(nonEmpty) == NumPiles || len(nonEmpty) == 0 {
		return false
	}
	newPiles := make([][]CardType, NumPiles)
	target := NumPiles - 1
	for i := len(nonEmpty) - 1; i >= 0 && target >= 0; i-- {
		newPiles[target] = nonEmpty[i]
		target--
	}
	changed := false
	for i := range g.Piles {
		if len(g.Piles[i]) != len(newPiles[i]) {
			changed = true
			break
		}
		for j := range g.Piles[i] {
			if g.Piles[i][j] != newPiles[i][j] {
				changed = true
				break
			}
		}
		if changed {
			break
		}
	}
	if changed {
		g.Piles = newPiles
		return true
	}
	return false
}

// DrawCardsForRound draws one card per non-empty pile, continuing from a pile until a non-Animatronic is drawn.
func (g *GameState) DrawCardsForRound() []DrawnCard {
	var drawn []DrawnCard
	for i := 0; i < NumPiles; i++ {
		for len(g.Piles[i]) > 0 {
			card := g.Piles[i][0]
			g.Piles[i] = g.Piles[i][1:]
			drawn = append(drawn, DrawnCard{Card: card, PileIdx: i})
			if card != CardAnimatronic {
				break
			}
		}
	}
	return drawn
}

// ApplyReactions shuffles reacted Animatronics back into their piles. Returns events.
func (g *GameState) ApplyReactions(reactions []DrawnCard) []ResolutionEvent {
	var events []ResolutionEvent
	for _, dc := range reactions {
		if dc.Card == CardAnimatronic {
			events = append(events, ResolutionEvent{Kind: EvAnimatronicReshuffled, Data: dc.PileIdx})
			g.Piles[dc.PileIdx] = append(g.Piles[dc.PileIdx], CardAnimatronic)
			rand.Shuffle(len(g.Piles[dc.PileIdx]), func(a, b int) {
				g.Piles[dc.PileIdx][a], g.Piles[dc.PileIdx][b] = g.Piles[dc.PileIdx][b], g.Piles[dc.PileIdx][a]
			})
		}
	}
	return events
}

// RollPowerDie returns a random power die result (0, 5, or 10).
func RollPowerDie() int {
	return PowerDieFaces[rand.Intn(len(PowerDieFaces))]
}

// CalculateAndApplyPowerCost deducts power for reactions and power drains. Returns total cost.
func (g *GameState) CalculateAndApplyPowerCost(reactions []DrawnCard, originalDrawn []DrawnCard) int {
	if len(reactions) == 0 {
		return 0
	}
	cost := 0
	for range reactions {
		cost += RollPowerDie()
	}
	for _, dc := range originalDrawn {
		if dc.Card == CardPowerDrain {
			cost += PowerDrainCost
		}
	}
	g.Power -= cost
	return cost
}

func (g *GameState) moveCardRandomlyIntoPile(card CardType, targetPile int) {
	p := g.Piles[targetPile]
	insertAt := rand.Intn(len(p) + 1)
	newPile := make([]CardType, len(p)+1)
	copy(newPile, p[:insertAt])
	newPile[insertAt] = card
	copy(newPile[insertAt+1:], p[insertAt:])
	g.Piles[targetPile] = newPile
}

func (g *GameState) moveCardToTopOfPile(card CardType, targetPile int) {
	g.Piles[targetPile] = append([]CardType{card}, g.Piles[targetPile]...)
}

func (g *GameState) loseGame(reason string) {
	g.GameOver = true
	g.Win = false
	_ = reason
}

// ResolveRemainingCards resolves cards in order Pile 4 down to Pile 1. Returns events and stops on loss.
func (g *GameState) ResolveRemainingCards(remaining []DrawnCard) []ResolutionEvent {
	var events []ResolutionEvent
	if len(remaining) == 0 {
		return events
	}
	// Sort by pile index descending (Pile 4 first).
	cardsToProcess := make([]DrawnCard, len(remaining))
	copy(cardsToProcess, remaining)
	for i := 0; i < len(cardsToProcess); i++ {
		for j := i + 1; j < len(cardsToProcess); j++ {
			if cardsToProcess[j].PileIdx > cardsToProcess[i].PileIdx {
				cardsToProcess[i], cardsToProcess[j] = cardsToProcess[j], cardsToProcess[i]
			}
		}
	}
	processed := make(map[int]bool)
	idx := 0
	for idx < len(cardsToProcess) {
		if processed[idx] {
			idx++
			continue
		}
		dc := cardsToProcess[idx]
		card, pileIdx := dc.Card, dc.PileIdx

		switch card {
		case CardAnimatronic:
			nextPile := pileIdx + 1
			if nextPile >= NumPiles {
				reason := "Animatronic moved past Pile 4!"
				g.loseGame(reason)
				events = append(events, ResolutionEvent{Kind: EvLoseGame, Data: reason})
				return events
			}
			g.moveCardRandomlyIntoPile(card, nextPile)
			events = append(events, ResolutionEvent{Kind: EvAnimatronicMoved, Data: [2]int{pileIdx, nextPile}})

		case CardWhatDown:
			if len(g.Piles[pileIdx]) == 0 {
				events = append(events, ResolutionEvent{Kind: EvPileEmpty, Data: pileIdx})
			} else {
				replacement := g.Piles[pileIdx][0]
				g.Piles[pileIdx] = g.Piles[pileIdx][1:]
				events = append(events, ResolutionEvent{Kind: EvDrawReplacement, Data: replacement})
				insertAt := idx + 1
				for insertAt < len(cardsToProcess) && cardsToProcess[insertAt].PileIdx > pileIdx {
					insertAt++
				}
				newCard := DrawnCard{Card: replacement, PileIdx: pileIdx}
				cardsToProcess = append(cardsToProcess, DrawnCard{})
				copy(cardsToProcess[insertAt+1:], cardsToProcess[insertAt:])
				cardsToProcess[insertAt] = newCard
			}

		case CardWhatRight:
			if len(g.Piles[pileIdx]) == 0 {
				events = append(events, ResolutionEvent{Kind: EvPileEmpty, Data: pileIdx})
			} else {
				moved := g.Piles[pileIdx][0]
				g.Piles[pileIdx] = g.Piles[pileIdx][1:]
				nextPile := pileIdx + 1
				if nextPile >= NumPiles {
					events = append(events, ResolutionEvent{Kind: EvRevealCard, Data: moved})
					if moved == CardAnimatronic {
						reason := "Animatronic moved past Pile 4 via Right Arrow!"
						g.loseGame(reason)
						events = append(events, ResolutionEvent{Kind: EvLoseGame, Data: reason})
						return events
					}
				} else {
					g.moveCardToTopOfPile(moved, nextPile)
				}
			}

		case CardWhatDoubleRight:
			if len(g.Piles[pileIdx]) == 0 {
				events = append(events, ResolutionEvent{Kind: EvPileEmpty, Data: pileIdx})
			} else {
				moved := g.Piles[pileIdx][0]
				g.Piles[pileIdx] = g.Piles[pileIdx][1:]
				nextPile := pileIdx + 2
				if nextPile >= NumPiles {
					events = append(events, ResolutionEvent{Kind: EvRevealCard, Data: moved})
					if moved == CardAnimatronic {
						reason := "Animatronic moved past Pile 4 via Double Right Arrow!"
						g.loseGame(reason)
						events = append(events, ResolutionEvent{Kind: EvLoseGame, Data: reason})
						return events
					}
				} else {
					g.moveCardToTopOfPile(moved, nextPile)
				}
			}

		case CardEmptyRoom, CardPowerDrain:
			// no effect
		}
		processed[idx] = true
		idx++
	}
	return events
}
