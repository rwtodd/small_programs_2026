package main

import (
	"math/rand"
	"time"
)

func main() {
	rand.Seed(time.Now().UnixNano())
	controller := NewGameController()
	controller.PlayGame()
}

// GameController runs the game loop and coordinates state and UI.
type GameController struct {
	state *GameState
	ui    *TextUI
}

func NewGameController() *GameController {
	return &GameController{
		state: NewGameState(),
		ui:    nil, // set after state
	}
}

func (c *GameController) PlayGame() {
	c.ui = NewTextUI(c.state)
	c.ui.displayMessage("Starting the Five Nights at Freddy's Game...")
	c.ui.displayState(true)

	for !c.state.IsGameOver() {
		c.state.AdvanceRound()
		if c.state.IsGameOver() {
			break
		}
		c.ui.displayRoundStart()

		if c.state.ConsolidatePiles() {
			c.ui.displayMessage("Piles consolidated upwards.")
		}
		c.ui.displayState(true)

		drawn := c.state.DrawCardsForRound()
		allEmpty := true
		for _, n := range c.state.GetPileSizes() {
			if n != 0 {
				allEmpty = false
				break
			}
		}
		if len(drawn) == 0 && allEmpty {
			c.ui.displayMessage("\nAll piles are empty.")
			c.ui.promptNextRound()
			continue
		}

		reactions, remaining := c.ui.getPlayerReactions(drawn)
		cost := c.state.CalculateAndApplyPowerCost(reactions, drawn)
		c.ui.displayPowerCost(cost)

		resolutionEvents := c.state.ResolveRemainingCards(remaining)
		reactionEvents := c.state.ApplyReactions(reactions)
		allEvents := append(resolutionEvents, reactionEvents...)
		c.ui.displayResolutionEvents(allEvents)

		if c.state.IsGameOver() {
			break
		}
		c.ui.promptNextRound()
	}
	c.ui.displayGameOver()
}
