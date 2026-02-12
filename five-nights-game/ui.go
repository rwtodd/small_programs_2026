package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"strings"
)

const colWidth = 27

// TextUI handles terminal I/O for the game.
type TextUI struct {
	state *GameState
	in    *bufio.Scanner
}

func NewTextUI(state *GameState) *TextUI {
	return &TextUI{state: state, in: bufio.NewScanner(os.Stdin)}
}

func (u *TextUI) displayMessage(msg string) {
	fmt.Println(msg)
}

func (u *TextUI) displayRoundStart() {
	fmt.Printf("\n\n\n\n\n===== Starting Round %d/%d (%s) =====\n\n\n",
		u.state.CurrentRound+1, NumRounds, u.state.GetCurrentTime())
}

func (u *TextUI) displayState(showPiles bool) {
	fmt.Println("------------------------------")
	fmt.Printf("Time: %s\n", u.state.GetCurrentTime())
	fmt.Printf("Power: %d%%\n", u.state.GetPower())
	if showPiles {
		fmt.Printf("Pile sizes: %v\n", u.state.GetPileSizes())
	}
	fmt.Println("------------------------------")
}

// displayDrawnCardsFormatted prints drawn cards and returns display number (1-based) -> index in drawn slice.
func (u *TextUI) displayDrawnCardsFormatted(drawn []DrawnCard) map[int]int {
	fmt.Println("\n--- Cards Drawn This Round ---")
	if len(drawn) == 0 {
		fmt.Println("No cards were drawn.")
		return nil
	}
	cardsByPile := make(map[int][]struct {
		card   CardType
		dispNum int
	})
	displayNumToDrawnIdx := make(map[int]int)
	displayNum := 1
	for idx, dc := range drawn {
		if dc.PileIdx >= 0 && dc.PileIdx < NumPiles {
			cardsByPile[dc.PileIdx] = append(cardsByPile[dc.PileIdx], struct {
				card   CardType
				dispNum int
			}{dc.Card, displayNum})
			displayNumToDrawnIdx[displayNum] = idx
			displayNum++
		} else {
			fmt.Printf("Warning: Invalid pile index %d encountered for card %s\n", dc.PileIdx, dc.Card)
		}
	}
	maxCardsInPile := 0
	for i := 0; i < NumPiles; i++ {
		if n := len(cardsByPile[i]); n > maxCardsInPile {
			maxCardsInPile = n
		}
	}
	headerLine := ""
	for i := 0; i < NumPiles; i++ {
		headerLine += padRight(fmt.Sprintf("Pile %d", i+1), colWidth)
	}
	fmt.Println(headerLine)
	sepLine := ""
	for i := 0; i < NumPiles; i++ {
		s := "-----"
		if len(cardsByPile[i]) > 0 {
			s = strings.Repeat("-", len(fmt.Sprintf("Pile %d", i+1)))
		}
		sepLine += padRight(s, colWidth)
	}
	fmt.Println(sepLine)
	for row := 0; row < maxCardsInPile; row++ {
		line1 := ""
		line2 := ""
		needsLine2 := false
		for i := 0; i < NumPiles; i++ {
			content := cardsByPile[i]
			if row < len(content) {
				card := content[row].card
				dispNum := content[row].dispNum
				part1, part2 := card.DisplayName()
				line1 += padRight(fmt.Sprintf("(%d) %s", dispNum, part1), colWidth)
				if part2 != "" {
					line2 += padRight("    "+part2, colWidth)
					needsLine2 = true
				} else {
					line2 += padRight("", colWidth)
				}
			} else {
				line1 += padRight("", colWidth)
				line2 += padRight("", colWidth)
			}
		}
		fmt.Println(line1)
		if needsLine2 {
			fmt.Println(line2)
		}
		if row < maxCardsInPile-1 {
			spacerNeeded := false
			for p := 0; p < NumPiles; p++ {
				if row+1 < len(cardsByPile[p]) {
					spacerNeeded = true
					break
				}
			}
			if spacerNeeded {
				fmt.Println()
			}
		}
	}
	fmt.Println(strings.Repeat("-", colWidth*NumPiles))
	return displayNumToDrawnIdx
}

func padRight(s string, w int) string {
	if len(s) >= w {
		return s
	}
	return s + strings.Repeat(" ", w-len(s))
}

// getPlayerReactions returns (reactions, remaining cards).
func (u *TextUI) getPlayerReactions(drawn []DrawnCard) (reactions []DrawnCard, remaining []DrawnCard) {
	displayNumMap := u.displayDrawnCardsFormatted(drawn)
	if displayNumMap == nil {
		remaining = append(remaining, drawn...)
		return nil, remaining
	}
	if u.state.GetPower() <= 0 {
		fmt.Println("\nPower is 0% or less. Cannot react.")
		remaining = append(remaining, drawn...)
		return nil, remaining
	}
	unchosen := make([]*DrawnCard, len(drawn))
	for i := range drawn {
		unchosen[i] = &drawn[i]
	}
	var chosenReactions []DrawnCard
	reactedDisplayNums := make(map[int]bool)

	for len(chosenReactions) < MaxReactions {
		remainingChoices := MaxReactions - len(chosenReactions)
		fmt.Printf("Choose card number(s) to react to (1-%d), up to %d total. Enter 0 to finish: ", len(displayNumMap), remainingChoices)
		if !u.in.Scan() {
			break
		}
		inputStr := strings.TrimSpace(u.in.Text())
		if inputStr == "" {
			continue
		}
		choicesStr := strings.Fields(inputStr)
		hasZero := false
		for _, s := range choicesStr {
			if s == "0" {
				hasZero = true
				break
			}
		}
		if hasZero && len(choicesStr) > 1 {
			fmt.Println("Invalid input: Cannot mix 0 with other numbers.")
			continue
		}
		if hasZero || inputStr == "0" {
			break
		}
		if len(choicesStr)+len(chosenReactions) > MaxReactions {
			fmt.Printf("Invalid input: Cannot choose %d card(s), only %d reaction(s) left.\n", len(choicesStr), remainingChoices)
			continue
		}
		currentSelection := make(map[int]bool)
		var currentData []DrawnCard
		valid := true
		for _, choiceStr := range choicesStr {
			displayNum, err := strconv.Atoi(choiceStr)
			if err != nil {
				fmt.Println("Invalid input. Enter numbers separated by spaces, or 0.")
				valid = false
				break
			}
			if displayNum < 1 || displayNum > len(displayNumMap) {
				fmt.Printf("Invalid input: '%d' is not a valid card number.\n", displayNum)
				valid = false
				break
			}
			if reactedDisplayNums[displayNum] {
				fmt.Printf("Invalid input: Already chose card %d.\n", displayNum)
				valid = false
				break
			}
			if currentSelection[displayNum] {
				fmt.Printf("Invalid input: Cannot choose %d twice.\n", displayNum)
				valid = false
				break
			}
			drawnIdx := displayNumMap[displayNum]
			dc := drawn[drawnIdx]
			if !reactableCards[dc.Card] {
				fmt.Printf("Invalid input: Card %d ('%s') cannot be reacted to.\n", displayNum, dc.Card)
				valid = false
				break
			}
			currentSelection[displayNum] = true
			currentData = append(currentData, dc)
		}
		if !valid {
			continue
		}
		chosenReactions = append(chosenReactions, currentData...)
		for d := range currentSelection {
			reactedDisplayNums[d] = true
			unchosen[displayNumMap[d]] = nil
		}
		if len(chosenReactions) >= MaxReactions {
			break
		}
	}
	for _, dc := range unchosen {
		if dc != nil {
			remaining = append(remaining, *dc)
		}
	}
	return chosenReactions, remaining
}

func (u *TextUI) displayPowerCost(cost int) {
	fmt.Println("\n--- Power Cost Assessment ---")
	fmt.Printf("Power cost this round: %d\n", cost)
	if cost > 0 {
		fmt.Printf("Power level updated: %d%%\n", u.state.GetPower())
		if u.state.GetPower() <= 0 {
			fmt.Println("WARNING: Power depleted!")
		}
	}
}

func (u *TextUI) displayResolutionEvents(events []ResolutionEvent) {
	if len(events) == 0 {
		return
	}
	fmt.Println("\n--- Resolution Events ---")
	for _, e := range events {
		switch e.Kind {
		case EvRevealCard:
			fmt.Printf("  Card moved past Pile 4 and discarded: %v\n", e.Data)
		case EvDrawReplacement:
			fmt.Printf("  Down Arrow drew replacement card: %v\n", e.Data)
		case EvPileEmpty:
			fmt.Printf("  Attempted to draw/move from empty Pile %d.\n", e.Data.(int)+1)
		case EvAnimatronicMoved:
			arr := e.Data.([2]int)
			fmt.Printf("  Animatronic moved from Pile %d to Pile %d (shuffled in).\n", arr[0]+1, arr[1]+1)
		case EvAnimatronicReshuffled:
			fmt.Printf("  Animatronic re-shuffled into Pile %d.\n", e.Data.(int)+1)
		case EvLoseGame:
			fmt.Printf("  !!! GAME OVER: %v\n", e.Data)
		}
	}
}

func (u *TextUI) displayGameOver() {
	fmt.Println("\n==============================")
	if u.state.DidWin() {
		fmt.Println("  YOU SURVIVED THE NIGHT - YOU WIN!")
	} else {
		fmt.Println("          GAME OVER - YOU LOST!")
	}
	fmt.Println("==============================")
}

func (u *TextUI) promptNextRound() {
	fmt.Print("\nPress Enter to continue to the next round...")
	u.in.Scan()
}
